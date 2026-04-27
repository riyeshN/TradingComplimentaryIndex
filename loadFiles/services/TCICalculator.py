import numpy as np
import pandas as pd
from pathlib import Path
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

EXPORT_DIR = "./data/TradeMapData/export/"
HS_CHAPTERS_TO_INCLUDE = ['84', '85', '86', '87', '88', '89', '90']
YEARS_TO_INCLUDE = [str(y) for y in range(2001, 2025)]


class TCICalculator:
    """
    Calculates Trade Complementarity Index (TCI) using two formulas:
      - Drysdale & Garnaut:  (Xi_k/Xi) × (Mj_k/Mj) × (WX/WX_k)
      - RCA-based:           RCA_export × RCA_import × proportion_world_trade
        (algebraically identical to Drysdale & Garnaut; used as a cross-check)

    Data is read from the database (loaded by TradeMapLoader).
    Results are exported as a two-sheet Excel workbook per partner to EXPORT_DIR.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

        # Built during processing — keyed by partner ("China" or "US")
        self.hs6_trade_data_by_partner: dict[str, pd.DataFrame] = {}
        self.hs4_index_by_partner:      dict[str, pd.DataFrame] = {}
        self.hs6_weighted_by_partner:   dict[str, pd.DataFrame] = {}

    # ── Public entry point ───────────────────────────────────────────────────

    def run(self, countries: list[str] | None = None, hs4_codes: list[str] | None = None):
        self._load_from_db()
        self._filter_by_hs_chapter_and_year()
        self._calculate_tci_drysdale_garnaut()
        self._calculate_rca_and_tci_rca()
        self._aggregate_hs6_to_hs4()
        self._export_excel(countries, hs4_codes)
        self._export_hs4_tci_charts(countries, hs4_codes)

    # ── Load from DB ─────────────────────────────────────────────────────────

    def _load_from_db(self):
        """
        Query all four trade tables directly in long format, extract TOTAL rows
        as per-year denominators, then merge into one master DataFrame per partner.
        """
        from loadFiles.models import (
            CountryExportToPartner, CountryExportToWorld,
            PartnerImportFromWorld, WorldExport, HSProduct,
        )

        # ── Raw long-format queries ──────────────────────────────────────────

        bilateral_records = list(
            CountryExportToPartner.objects.values('reporter', 'partner', 'product_code', 'year', 'value_usd_thousands')
        )
        reporter_world_records = list(
            CountryExportToWorld.objects.values('reporter', 'product_code', 'year', 'value_usd_thousands')
        )
        partner_import_records = list(
            PartnerImportFromWorld.objects.values('partner', 'product_code', 'year', 'value_usd_thousands')
        )
        world_export_records = list(
            WorldExport.objects.values('product_code', 'year', 'value_usd_thousands')
        )

        if not world_export_records:
            self.logger.error("No WorldExport data in DB. Run TradeMapLoader first.")
            return

        hs_label_by_product_code = dict(HSProduct.objects.values_list('product_code', 'product_label'))

        bilateral_df = pd.DataFrame(bilateral_records).rename(columns={
            'reporter': 'Country',
            'product_code': 'Product code',
            'year': 'Year',
            'value_usd_thousands': 'Reporter Export To Partner',
        })

        reporter_world_df = pd.DataFrame(reporter_world_records).rename(columns={
            'reporter': 'Country',
            'product_code': 'Product code',
            'year': 'Year',
            'value_usd_thousands': 'Reporter Export To World',
        })

        partner_import_df = pd.DataFrame(partner_import_records).rename(columns={
            'product_code': 'Product code',
            'year': 'Year',
            'value_usd_thousands': 'Partner Import From World',
        })

        world_export_df = pd.DataFrame(world_export_records).rename(columns={
            'product_code': 'Product code',
            'year': 'Year',
            'value_usd_thousands': 'World Export of item k',
        })
        world_export_df['Product label'] = (
            world_export_df['Product code'].map(hs_label_by_product_code).fillna('All products')
        )

        # Ensure Year is string for consistent joining
        for df in [bilateral_df, reporter_world_df, partner_import_df, world_export_df]:
            df['Year'] = df['Year'].astype(str)

        # ── Extract TOTAL rows as denominator lookup tables ──────────────────

        def is_total(series: pd.Series) -> pd.Series:
            return series.astype(str).str.upper() == 'TOTAL'

        reporter_totals = (
            reporter_world_df[is_total(reporter_world_df['Product code'])]
            [['Country', 'Year', 'Reporter Export To World']]
            .rename(columns={'Reporter Export To World': "Reporter's Total Export To World"})
        )

        partner_totals = (
            partner_import_df[is_total(partner_import_df['Product code'])]
            [['partner', 'Year', 'Partner Import From World']]
            .rename(columns={'Partner Import From World': "Partner's Total Import From World"})
        )

        world_totals = (
            world_export_df[is_total(world_export_df['Product code'])]
            [['Year', 'World Export of item k']]
            .rename(columns={'World Export of item k': 'Total World Export'})
        )

        # ── Drop TOTAL rows from product-level data ──────────────────────────

        bilateral_df      = bilateral_df[~is_total(bilateral_df['Product code'])]
        reporter_world_df = reporter_world_df[~is_total(reporter_world_df['Product code'])]
        partner_import_df = partner_import_df[~is_total(partner_import_df['Product code'])]
        world_export_df   = world_export_df[~is_total(world_export_df['Product code'])]

        world_export_product_labels = (
            world_export_df[['Product code', 'Product label']].drop_duplicates('Product code')
        )

        # Precompute true HS4-level world totals across ALL HS6 codes in each heading.
        # This ensures the denominator in HS4 RCA/TCI is reporter-independent, even when
        # reporters have different HS6 universes (e.g. due to the HS 2007 revision of 8542).
        world_hs4_totals_df = (
            world_export_df.assign(HS4=world_export_df['Product code'].astype(str).str[:4])
            .groupby(['HS4', 'Year'], as_index=False)['World Export of item k']
            .sum()
            .rename(columns={'World Export of item k': 'World Export HS4 Total'})
        )

        # ── Build merged DataFrame per partner ──────────────────────────────

        for partner_name in ['China', 'US']:
            reporters_for_partner = bilateral_df.loc[
                bilateral_df['partner'] == partner_name, 'Country'
            ].unique()

            if len(reporters_for_partner) == 0:
                self.logger.warning("No bilateral data for partner %s in DB.", partner_name)
                continue

            # Reporter→world: keep only reporters that have bilateral trade with this partner
            reporter_world_for_partner = reporter_world_df[
                reporter_world_df['Country'].isin(reporters_for_partner)
            ].copy()

            # Bilateral exports to this partner
            bilateral_for_partner = (
                bilateral_df[bilateral_df['partner'] == partner_name]
                .drop(columns=['partner'])
            )

            # Partner imports from world (same for all reporters)
            partner_imports_for_partner = (
                partner_import_df[partner_import_df['partner'] == partner_name]
                .drop(columns=['partner'])
            )

            # Partner denominator (total imports)
            partner_total_for_partner = (
                partner_totals[partner_totals['partner'] == partner_name]
                .drop(columns=['partner'])
            )

            merged = reporter_world_for_partner.merge(
                bilateral_for_partner, on=['Country', 'Year', 'Product code'], how='left'
            )
            merged = merged.merge(
                partner_imports_for_partner, on=['Year', 'Product code'], how='left'
            )
            merged = merged.merge(
                world_export_df[['Year', 'Product code', 'World Export of item k']],
                on=['Year', 'Product code'], how='left'
            )
            merged = merged.merge(
                world_export_product_labels, on='Product code', how='left'
            )
            merged = merged.merge(
                reporter_totals, on=['Country', 'Year'], how='left'
            )
            merged = merged.merge(
                partner_total_for_partner, on=['Year'], how='left'
            )
            merged = merged.merge(
                world_totals, on=['Year'], how='left'
            )

            merged['HS4'] = merged['Product code'].astype(str).str[:4]
            merged = merged.merge(world_hs4_totals_df, on=['HS4', 'Year'], how='left')
            merged = merged.drop(columns=['HS4'])  # re-derived in _aggregate_hs6_to_hs4

            merged[['Reporter Export To Partner', 'Partner Import From World']] = (
                merged[['Reporter Export To Partner', 'Partner Import From World']].fillna(0)
            )

            merged = merged[[
                'Country', 'Year', 'Product code', 'Product label',
                'Reporter Export To Partner',
                'Reporter Export To World',
                'Partner Import From World',
                'World Export of item k',
                "Reporter's Total Export To World",
                "Partner's Total Import From World",
                'Total World Export',
                'World Export HS4 Total',
            ]]

            merged.sort_values(
                by=['Product code', 'Year'], ascending=[True, False],
                inplace=True, ignore_index=True,
            )

            self.hs6_trade_data_by_partner[partner_name] = merged
            self.logger.info("Loaded and merged %d rows for partner %s.", len(merged), partner_name)

    # ── Pipeline steps ───────────────────────────────────────────────────────

    def _filter_by_hs_chapter_and_year(self):
        for partner_name, hs6_data in self.hs6_trade_data_by_partner.items():
            chapter_mask = hs6_data['Product code'].astype(str).str[:2].str.upper().isin(HS_CHAPTERS_TO_INCLUDE)
            year_mask = hs6_data['Year'].astype(str).isin(YEARS_TO_INCLUDE)
            self.hs6_trade_data_by_partner[partner_name] = hs6_data[chapter_mask & year_mask]

    def _calculate_tci_drysdale_garnaut(self):
        """TCI = (Xi_k / Xi) × (Mj_k / Mj) × (WX / WX_k)"""
        for partner_name, hs6_data in self.hs6_trade_data_by_partner.items():
            reporter_export_share = hs6_data["Reporter Export To World"] / hs6_data["Reporter's Total Export To World"].replace(0, np.nan)
            partner_import_share  = hs6_data["Partner Import From World"] / hs6_data["Partner's Total Import From World"].replace(0, np.nan)
            inverse_world_share   = hs6_data["Total World Export"] / hs6_data["World Export of item k"].replace(0, np.nan)

            hs6_data["TCI_Drysdale_Garnaut"] = (
                reporter_export_share * partner_import_share * inverse_world_share
            ).fillna(0)

            self.hs6_trade_data_by_partner[partner_name] = hs6_data
            self.logger.info("TCI (Drysdale & Garnaut) calculated for partner %s.", partner_name)

    def _calculate_rca_and_tci_rca(self):
        """
        RCA_export = (Xi_k/Xi) / (WX_k/WX)
        RCA_import = (Mj_k/Mj) / (WX_k/WX)
        TCI_RCA    = RCA_export × RCA_import × (WX_k/WX)
        Algebraically equals TCI_Drysdale_Garnaut; used as a validation cross-check.
        """
        for partner_name, hs6_data in self.hs6_trade_data_by_partner.items():
            world_product_share = (
                hs6_data["World Export of item k"] / hs6_data["Total World Export"].replace(0, np.nan)
            ).replace(0, np.nan)

            hs6_data["RCA Reporter Export"] = (
                (hs6_data["Reporter Export To World"] / hs6_data["Reporter's Total Export To World"].replace(0, np.nan))
                / world_product_share
            ).fillna(0)

            hs6_data["RCA Partner Import"] = (
                (hs6_data["Partner Import From World"] / hs6_data["Partner's Total Import From World"].replace(0, np.nan))
                / world_product_share
            ).fillna(0)

            hs6_data["Proportion World Trade"] = (
                hs6_data["World Export of item k"] / hs6_data["Total World Export"]
            ).replace(0, np.nan).fillna(0)

            hs6_data["TCI Using RCA"] = (
                hs6_data["RCA Reporter Export"]
                * hs6_data["RCA Partner Import"]
                * hs6_data["Proportion World Trade"]
            )

            self.hs6_trade_data_by_partner[partner_name] = hs6_data

        self.logger.info("RCA and TCI (RCA) calculated.")

    def _aggregate_hs6_to_hs4(self):
        for partner_name, hs6_data in self.hs6_trade_data_by_partner.items():
            hs6_data = hs6_data.copy()
            hs6_data['HS4'] = hs6_data['Product code'].astype(str).str[:4]

            # Active pair: reporter had bilateral trade AND partner imports that product
            hs6_data['Active_Pair'] = (
                (hs6_data['Reporter Export To Partner'] > 0)
                & (hs6_data['Partner Import From World'] > 0)
            ).astype(int)

            active_hs4_group_export = hs6_data.loc[
                hs6_data['Active_Pair'] == 1
            ].groupby(['Country', 'Year', 'HS4'])['Reporter Export To World'].transform('sum')

            hs6_data['HS4 Group Trade'] = active_hs4_group_export

            hs6_data['HS4 Weight'] = np.where(
                hs6_data['Active_Pair'] == 1,
                hs6_data['Reporter Export To World'] / hs6_data['HS4 Group Trade'].replace(0, np.nan),
                0,
            )
            hs6_data['Cij Weighted']     = hs6_data['HS4 Weight'] * hs6_data['TCI_Drysdale_Garnaut']
            hs6_data['TCI RCA Weighted'] = hs6_data['HS4 Weight'] * hs6_data['TCI Using RCA']

            hs4_aggregated = (
                hs6_data.groupby(['Country', 'Year', 'HS4'])
                .agg(
                    Cij_Weighted                   = ('Cij Weighted',                    'sum'),
                    TradeComplimentary_RCA_Weighted = ('TCI RCA Weighted',                'sum'),
                    Total_Reporter_Export           = ('Reporter Export To World',         'sum'),
                    Total_Partner_Import            = ('Partner Import From World',        'sum'),
                    Total_World_Export_k            = ('World Export HS4 Total',           'first'),
                    Num_Active_HS6_Pairs            = ('Active_Pair',                     'sum'),
                    Reporter_Total_All_Products     = ("Reporter's Total Export To World", 'first'),
                    Partner_Total_All_Products      = ("Partner's Total Import From World",'first'),
                    World_Total_All_Products        = ('Total World Export',               'first'),
                )
                .reset_index()
            )

            hs4_aggregated['RCA_Export_4digit'] = (
                (hs4_aggregated['Total_Reporter_Export'] / hs4_aggregated['Reporter_Total_All_Products'].replace(0, np.nan))
                / (hs4_aggregated['Total_World_Export_k'] / hs4_aggregated['World_Total_All_Products'].replace(0, np.nan))
            )
            hs4_aggregated['RCA_Import_4digit'] = (
                (hs4_aggregated['Total_Partner_Import'] / hs4_aggregated['Partner_Total_All_Products'].replace(0, np.nan))
                / (hs4_aggregated['Total_World_Export_k'] / hs4_aggregated['World_Total_All_Products'].replace(0, np.nan))
            )
            hs4_aggregated['Proportion_World_Trade_4digit'] = (
                hs4_aggregated['Total_World_Export_k'] / hs4_aggregated['World_Total_All_Products'].replace(0, np.nan)
            )
            hs4_aggregated['TradeComplimentary_RCA_ReCalculated'] = (
                hs4_aggregated['RCA_Export_4digit']
                * hs4_aggregated['RCA_Import_4digit']
                * hs4_aggregated['Proportion_World_Trade_4digit']
            )

            # Zero-active groups should have zero weighted TCI (sanity guard)
            zero_active_mask = hs4_aggregated['Num_Active_HS6_Pairs'] == 0
            if zero_active_mask.any():
                bad_rows = hs4_aggregated.loc[zero_active_mask & (
                    (hs4_aggregated['Cij_Weighted'].abs() > 0)
                    | (hs4_aggregated['TradeComplimentary_RCA_Weighted'].abs() > 0)
                    | (hs4_aggregated['TradeComplimentary_RCA_ReCalculated'].abs() > 0)
                )]
                if not bad_rows.empty:
                    self.logger.warning(
                        "Zero-active HS4 groups with nonzero TCI for partner %s:\n%s",
                        partner_name,
                        bad_rows[['Country', 'Year', 'HS4', 'Cij_Weighted']],
                    )
                hs4_aggregated.loc[zero_active_mask, [
                    'Cij_Weighted', 'TradeComplimentary_RCA_Weighted', 'TradeComplimentary_RCA_ReCalculated',
                ]] = 0

            hs4_aggregated = hs4_aggregated[[
                'Country', 'Year', 'HS4',
                'Cij_Weighted', 'TradeComplimentary_RCA_Weighted', 'TradeComplimentary_RCA_ReCalculated',
                'RCA_Export_4digit', 'RCA_Import_4digit', 'Proportion_World_Trade_4digit',
                'Total_Reporter_Export', 'Total_Partner_Import', 'Total_World_Export_k',
                'Num_Active_HS6_Pairs',
            ]]

            self.hs4_index_by_partner[partner_name]    = hs4_aggregated
            self.hs6_weighted_by_partner[partner_name] = hs6_data

    # ── Export ───────────────────────────────────────────────────────────────

    def _export_excel(self, countries: list[str] | None, hs4_codes: list[str] | None):
        export_dir = Path(EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)

        hs4_summary_columns = {
            'Country':                    'Country',
            'Year':                       'Year',
            'HS4':                        'HS4',
            'Cij_Weighted':               'TCI_Drysdale_Garnaut',
            'TradeComplimentary_RCA_Weighted': 'TCI_RCA',
            'RCA_Export_4digit':          'RCA_Reporter_Export',
            'RCA_Import_4digit':          'RCA_Partner_Import',
            'Proportion_World_Trade_4digit': 'Proportion_World_Trade',
            'Total_Reporter_Export':      'Total_Reporter_Export_USD_thousands',
            'Total_Partner_Import':       'Total_Partner_Import_USD_thousands',
            'Total_World_Export_k':       'Total_World_Export_USD_thousands',
            'Num_Active_HS6_Pairs':       'Active_HS6_Pairs',
        }

        hs6_detail_columns = {
            'Country':                          'Country',
            'Year':                             'Year',
            'HS4':                              'HS4',
            'Product code':                     'Product_Code',
            'Product label':                    'Product_Label',
            'Reporter Export To Partner':       'Reporter_Export_To_Partner_USD_thousands',
            'Reporter Export To World':         'Reporter_Export_To_World_USD_thousands',
            'Partner Import From World':        'Partner_Import_From_World_USD_thousands',
            'World Export of item k':           'World_Export_HS6_USD_thousands',
            'World Export HS4 Total':           'World_Export_HS4_Total_USD_thousands',
            "Reporter's Total Export To World": 'Total_Reporter_Export_USD_thousands',
            "Partner's Total Import From World":'Total_Partner_Import_USD_thousands',
            'Total World Export':               'Total_World_Export_USD_thousands',
            'TCI_Drysdale_Garnaut':             'TCI_Drysdale_Garnaut',
            'RCA Reporter Export':              'RCA_Reporter_Export',
            'RCA Partner Import':               'RCA_Partner_Import',
            'Proportion World Trade':           'Proportion_World_Trade',
            'TCI Using RCA':                    'TCI_RCA',
            'Active_Pair':                      'Active_Pair',
            'HS4 Group Trade':                  'HS4_Group_Trade',
            'HS4 Weight':                       'HS4_Weight',
            'Cij Weighted':                     'HS6_TCI_Drysdale_Garnaut_Weighted',
            'TCI RCA Weighted':                 'HS6_TCI_RCA_Weighted',
        }

        for partner_name in self.hs4_index_by_partner:
            hs4_data = self.hs4_index_by_partner[partner_name].copy()
            hs6_data = self.hs6_weighted_by_partner[partner_name].copy()

            if countries is not None:
                hs4_data = hs4_data[hs4_data['Country'].isin(countries)]
                hs6_data = hs6_data[hs6_data['Country'].isin(countries)]

            if hs4_codes is not None:
                hs4_data = hs4_data[hs4_data['HS4'].isin(hs4_codes)]
                hs6_data = hs6_data[hs6_data['HS4'].isin(hs4_codes)]

            hs4_sheet = (
                hs4_data[list(hs4_summary_columns.keys())]
                .rename(columns=hs4_summary_columns)
                .sort_values(['Country', 'Year', 'HS4'])
                .reset_index(drop=True)
            )
            hs6_sheet = (
                hs6_data[list(hs6_detail_columns.keys())]
                .rename(columns=hs6_detail_columns)
                .sort_values(['Country', 'Year', 'HS4', 'Product_Code'])
                .reset_index(drop=True)
            )

            output_path = export_dir / f"{partner_name}_TCI.xlsx"
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                hs4_sheet.to_excel(writer, sheet_name='HS4 Summary', index=False)
                hs6_sheet.to_excel(writer, sheet_name='HS6 Detail', index=False)

            self.logger.info("Exported %s (%d HS4 rows, %d HS6 rows).", output_path, len(hs4_sheet), len(hs6_sheet))

    def _export_hs4_tci_charts(self, countries: list[str] | None, hs4_codes: list[str] | None):
        export_dir = Path(EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)

        for partner_name, hs4_data in self.hs4_index_by_partner.items():
            data = hs4_data.copy()

            if countries is not None:
                data = data[data['Country'].isin(countries)]
            if hs4_codes is not None:
                data = data[data['HS4'].isin(hs4_codes)]

            data = data.copy()
            data['Year'] = pd.to_numeric(data['Year'], errors='coerce')
            data = data.dropna(subset=['Year', 'TradeComplimentary_RCA_Weighted'])
            data = data.sort_values('Year')

            for hs4_code in data['HS4'].unique():
                hs4_data_filtered = data[data['HS4'] == hs4_code]

                fig, ax = plt.subplots(figsize=(12, 6))
                for country_name in sorted(hs4_data_filtered['Country'].unique()):
                    country_rows = hs4_data_filtered[hs4_data_filtered['Country'] == country_name]
                    ax.plot(country_rows['Year'], country_rows['TradeComplimentary_RCA_Weighted'],
                            marker='o', label=country_name)

                ax.set_title(f'Trade Complementarity Index (RCA) — HS4 {hs4_code} — Partner: {partner_name}')
                ax.set_xlabel('Year')
                ax.set_ylabel('TCI (RCA)')
                ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
                ax.grid(True, linestyle='--', alpha=0.5)
                fig.tight_layout()
                fig.savefig(export_dir / f"{partner_name}_{hs4_code}_TCI_RCA.png")
                plt.close(fig)

        self.logger.info("HS4 TCI charts exported.")

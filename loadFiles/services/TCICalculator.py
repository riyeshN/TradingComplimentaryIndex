import logging
from pathlib import Path

import numpy as np
import pandas as pd

from loadFiles.services import trade_data_loader
from loadFiles.services.scope import Scope, SCOPE_ICT
from loadFiles.services.exporters import (
    export_excel, export_hs4_tci_charts, export_word_summary,
)

EXPORT_DIR = "./data/TradeMapData/export/"
YEARS_TO_INCLUDE = [str(y) for y in range(2001, 2025)]

# HS codes that were vacated and later re-used for a different product, so their
# pre-reintroduction years carry meaningless trade (near-zero world denominator →
# exploding RCA) and mix two different products in one series. Keyed by HS code
# prefix → first year the code is valid in its current meaning. Rows for that
# code prefix before the year are dropped from every scope.
#   8524: vacated in HS2007 (was "recorded media"); reintroduced in HS2022 as
#         "flat-panel display modules". Only 2022+ is a coherent series.
RESTRICTED_CODE_FIRST_VALID_YEAR = {'8524': 2022}


class TCICalculator:
    """
    Calculates Trade Complementarity Index (TCI) over the UNCTAD ICT goods scope
    (HS 2022, 23 HS4 headings, 107 HS6 codes) for Indo-Pacific reporters versus
    China and the United States.

    Three-tier output, all derived from a single HS6 source:
      - HS6 Cij (Drysdale-Garnaut)         — single-product values, audit trail.
      - HS4 Cij  = sum of HS6 Cij in heading — preserves bilateral product matching.
      - Headline = sum of HS6 Cij over scope — single Cij per (reporter, partner, year).

    Two TCI forms are reported at every tier:
      - Drysdale-Garnaut (weighted): (Xi_k/Xi) × (Mj_k/Mj) × (WX/WX_k)   — primary.
      - RCA product (unweighted):    RCA_export × RCA_import             — secondary.

    HS4 RCA is reported as an auxiliary heading-level specialisation metric. It is
    derived as a weighted average of HS6 RCA values with weight = (W_k / W_HS4),
    and is not used in the HS4 Cij calculation.

    Data is read from the database (loaded by TradeMapLoader).
    Results are exported as a three-sheet Excel workbook per partner to EXPORT_DIR.
    See README.md and docs/validation_methodology.md for the full methodology.
    """

    def __init__(self, scope: Scope = SCOPE_ICT,
                 partner_names: tuple[str, ...] = ('China', 'US')):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.scope = scope
        self.partner_names = partner_names

        # Built during processing — keyed by partner ("China"/"US", or "CCE" for Yang)
        self.hs6_trade_data_by_partner:      dict[str, pd.DataFrame] = {}
        self.hs4_index_by_partner:           dict[str, pd.DataFrame] = {}
        self.hs2_index_by_partner:           dict[str, pd.DataFrame] = {}
        self.sitc_index_by_partner:          dict[str, pd.DataFrame] = {}
        self.hs6_with_indicators_by_partner: dict[str, pd.DataFrame] = {}
        self.headline_cij_by_partner:        dict[str, pd.DataFrame] = {}

        # Precomputed totals from trade_data_loader — reporter-independent on
        # the world/partner side, partner-independent on the reporter side.
        self.world_hs4_totals_df:     pd.DataFrame | None = None
        self.partner_hs4_totals_df:   pd.DataFrame | None = None
        self.reporter_hs4_totals_df:  pd.DataFrame | None = None
        self.world_hs2_totals_df:     pd.DataFrame | None = None
        self.partner_hs2_totals_df:   pd.DataFrame | None = None
        self.reporter_hs2_totals_df:  pd.DataFrame | None = None
        self.world_sitc_totals_df:    pd.DataFrame | None = None
        self.partner_sitc_totals_df:  pd.DataFrame | None = None
        self.reporter_sitc_totals_df: pd.DataFrame | None = None
        self.reporter_totals_df:      pd.DataFrame | None = None
        self.partner_totals_df:       pd.DataFrame | None = None
        self.world_totals_df:         pd.DataFrame | None = None

    # ── Public entry points ──────────────────────────────────────────────────

    def run_indicators(self):
        """Load + compute every Cij/RCA tier, no file export. Shared by run()
        and by validation commands so they read identical pipeline output."""
        self._load_from_db()
        self._filter_by_scope_and_year()
        self._calculate_tci_drysdale_garnaut()
        self._calculate_rca_and_tci_rca()
        self._aggregate_hs6_to_hs4()
        if self.scope.primary_tier == 'HS2':
            self._aggregate_hs4_to_hs2()
        if self.scope.primary_tier == 'SITC':
            self._aggregate_to_sitc()
        self._calculate_headline_cij()
        self._verify_partner_invariants()

    def run(self, countries: list[str] | None = None, hs4_codes: list[str] | None = None):
        self.run_indicators()
        self._export_excel(countries, hs4_codes)
        self._export_hs4_tci_charts(countries, hs4_codes)
        self._export_word_summary(countries, hs4_codes)

    # ── Load from DB ─────────────────────────────────────────────────────────

    def _load_from_db(self):
        """Delegate to trade_data_loader — pure DB → long-format DataFrames."""
        bundle = trade_data_loader.load_all(
            partner_names=self.partner_names, logger=self.logger,
        )
        if bundle is None:
            return
        self.hs6_trade_data_by_partner = bundle.hs6_per_partner
        self.world_hs4_totals_df       = bundle.world_hs4_totals
        self.partner_hs4_totals_df     = bundle.partner_hs4_totals
        self.reporter_hs4_totals_df    = bundle.reporter_hs4_totals
        self.world_hs2_totals_df       = bundle.world_hs2_totals
        self.partner_hs2_totals_df     = bundle.partner_hs2_totals
        self.reporter_hs2_totals_df    = bundle.reporter_hs2_totals
        self.world_sitc_totals_df      = bundle.world_sitc_totals
        self.partner_sitc_totals_df    = bundle.partner_sitc_totals
        self.reporter_sitc_totals_df   = bundle.reporter_sitc_totals
        self.reporter_totals_df        = bundle.reporter_totals
        self.partner_totals_df         = bundle.partner_totals
        self.world_totals_df           = bundle.world_totals

    # ── Pipeline steps ───────────────────────────────────────────────────────

    def _filter_by_scope_and_year(self):
        """Filter HS6 rows by scope (HS-prefix match) and the configured year range.
        An empty `filter_codes` means no HS filter (keep the whole HS6 universe —
        used by the Yang scope, which spans all SITC sections)."""
        prefix_len  = self.scope.filter_digits
        prefix_set  = set(self.scope.filter_codes)
        for partner_name, hs6_data in self.hs6_trade_data_by_partner.items():
            product_code = hs6_data['Product code'].astype(str)
            year_numeric = pd.to_numeric(hs6_data['Year'], errors='coerce')
            year_mask = hs6_data['Year'].astype(str).isin(YEARS_TO_INCLUDE)
            if prefix_set:
                prefix = product_code.str[:prefix_len]
                mask = prefix.isin(prefix_set) & year_mask
            else:
                mask = year_mask
            # Drop vacated/re-used codes in the years before their current meaning.
            for code_prefix, first_valid_year in RESTRICTED_CODE_FIRST_VALID_YEAR.items():
                contaminated = product_code.str[:len(code_prefix)].eq(code_prefix) & (year_numeric < first_valid_year)
                mask &= ~contaminated
            self.hs6_trade_data_by_partner[partner_name] = hs6_data[mask]

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
        Balassa RCAs at HS6:
          RCA_export = (Xi_k/Xi) / (WX_k/WX)
          RCA_import = (Mj_k/Mj) / (WX_k/WX)

        TCI_RCA_DG_Decomposition = RCA_export × RCA_import × (WX_k/WX)
            — algebraically equal to TCI_Drysdale_Garnaut; internal consistency check.

        Active_Pair flag = 1 when reporter has world exports AND partner has world imports
        of the HS6 product. Counts the HS6 lines that contribute non-zero values to the
        TCI sum at HS4 and headline level.
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

            hs6_data["TCI_RCA_DG_Decomposition"] = (
                hs6_data["RCA Reporter Export"]
                * hs6_data["RCA Partner Import"]
                * hs6_data["Proportion World Trade"]
            )

            hs6_data["Active_Pair"] = (
                (hs6_data["Reporter Export To World"] > 0)
                & (hs6_data["Partner Import From World"] > 0)
            ).astype(int)

            self.hs6_trade_data_by_partner[partner_name] = hs6_data

        self.logger.info("HS6 RCA and DG-decomposition TCI calculated.")

    def _aggregate_hs6_to_hs4(self):
        """
        HS4 Cij = sum of HS6 Cij values within each HS4 heading. Preserves the
        bilateral-product matching information in HS6: a heading registers
        complementarity only where reporter and partner each have non-zero world
        flows of the same HS6 code.

        HS4 RCA is computed directly from HS4-level totals taken from canonical
        source tables — `Partner Import HS4 Total` (sum of all HS6 the partner
        imports), `Reporter Export HS4 Total` (sum of all HS6 the reporter
        exports), and `World Export HS4 Total` (sum of all HS6 world exports
        per heading). Reporter-independent and partner-independent on the
        respective sides by construction.
        """
        for partner_name, hs6_data in self.hs6_trade_data_by_partner.items():
            hs6_data = hs6_data.copy()
            hs6_data['HS4'] = hs6_data['Product code'].astype(str).str[:4]

            hs4_sums = (
                hs6_data.groupby(['Country', 'Year', 'HS4'])
                .agg(
                    TCI_DG_4digit         = ('TCI_Drysdale_Garnaut',     'sum'),
                    Total_Reporter_Export = ('Reporter Export To World', 'sum'),
                    Total_Partner_Import  = ('Partner Import From World','sum'),
                    Num_Active_HS6_Pairs  = ('Active_Pair',              'sum'),
                )
                .reset_index()
            )

            # Canonical-source HS4 totals — reporter-side from CountryExportToWorld,
            # partner-side from PartnerImportFromWorld, world-side from WorldExport.
            # Each is complete and reporter/partner-independent on its own side.
            partner_totals_for_partner = (
                self.partner_hs4_totals_df[self.partner_hs4_totals_df['partner'] == partner_name]
                .drop(columns=['partner'])
            )
            hs4_aggregated = (
                hs4_sums
                .merge(self.reporter_hs4_totals_df, on=['Country', 'Year', 'HS4'], how='left')
                .merge(partner_totals_for_partner,  on=['Year', 'HS4'],            how='left')
                .merge(self.world_hs4_totals_df,    on=['Year', 'HS4'],            how='left')
                .merge(self.reporter_totals_df,     on=['Country', 'Year'],        how='left')
                .merge(
                    self.partner_totals_df[self.partner_totals_df['partner'] == partner_name]
                        .drop(columns=['partner']),
                    on=['Year'], how='left',
                )
                .merge(self.world_totals_df, on=['Year'], how='left')
            )

            world_share_hs4 = (
                hs4_aggregated['World Export HS4 Total']
                / hs4_aggregated['Total World Export'].replace(0, np.nan)
            )
            hs4_aggregated['RCA_Export_4digit'] = (
                (
                    hs4_aggregated['Reporter Export HS4 Total']
                    / hs4_aggregated["Reporter's Total Export To World"].replace(0, np.nan)
                )
                / world_share_hs4
            ).fillna(0)
            hs4_aggregated['RCA_Import_4digit'] = (
                (
                    hs4_aggregated['Partner Import HS4 Total']
                    / hs4_aggregated["Partner's Total Import From World"].replace(0, np.nan)
                )
                / world_share_hs4
            ).fillna(0)
            # Unweighted RCA product (RCA_export × RCA_import). Matches the
            # per-product index published by Yang (2023) Table 3.
            hs4_aggregated['TCI_RCA_Product_4digit'] = (
                hs4_aggregated['RCA_Export_4digit'] * hs4_aggregated['RCA_Import_4digit']
            )

            # Surface raw HS4 totals under the names the Excel exporter expects.
            hs4_aggregated = hs4_aggregated.rename(columns={
                'World Export HS4 Total': 'Total_World_Export_K',
            })
            # Override the per-partner-frame reporter/partner sums with the
            # canonical-source HS4 totals so downstream consumers see complete
            # heading-level trade values.
            hs4_aggregated['Total_Reporter_Export'] = (
                hs4_aggregated['Reporter Export HS4 Total'].fillna(0)
            )
            hs4_aggregated['Total_Partner_Import'] = (
                hs4_aggregated['Partner Import HS4 Total'].fillna(0)
            )

            hs4_aggregated = hs4_aggregated[[
                'Country', 'Year', 'HS4',
                'TCI_DG_4digit', 'TCI_RCA_Product_4digit',
                'RCA_Export_4digit', 'RCA_Import_4digit',
                'Total_Reporter_Export', 'Total_Partner_Import', 'Total_World_Export_K',
                'Num_Active_HS6_Pairs',
            ]]

            self.hs4_index_by_partner[partner_name]           = hs4_aggregated
            self.hs6_with_indicators_by_partner[partner_name] = hs6_data

    def _aggregate_hs4_to_hs2(self):
        """
        HS2 Cij = sum of HS6 Cij values within each HS2 chapter (equivalently:
        sum of HS4 Cij within each HS2 chapter). HS2 RCA is computed directly
        from HS2-level totals taken from canonical source tables. Same pattern
        as `_aggregate_hs6_to_hs4`, one tier higher.
        """
        for partner_name, hs6_data in self.hs6_with_indicators_by_partner.items():
            hs6_data = hs6_data.copy()
            hs6_data['HS2'] = hs6_data['Product code'].astype(str).str[:2]

            hs2_sums = (
                hs6_data.groupby(['Country', 'Year', 'HS2'])
                .agg(
                    TCI_DG_2digit        = ('TCI_Drysdale_Garnaut',     'sum'),
                    Num_Active_HS6_Pairs = ('Active_Pair',              'sum'),
                )
                .reset_index()
            )

            partner_totals_for_partner = (
                self.partner_hs2_totals_df[self.partner_hs2_totals_df['partner'] == partner_name]
                .drop(columns=['partner'])
            )
            hs2_aggregated = (
                hs2_sums
                .merge(self.reporter_hs2_totals_df, on=['Country', 'Year', 'HS2'], how='left')
                .merge(partner_totals_for_partner,  on=['Year', 'HS2'],            how='left')
                .merge(self.world_hs2_totals_df,    on=['Year', 'HS2'],            how='left')
                .merge(self.reporter_totals_df,     on=['Country', 'Year'],        how='left')
                .merge(
                    self.partner_totals_df[self.partner_totals_df['partner'] == partner_name]
                        .drop(columns=['partner']),
                    on=['Year'], how='left',
                )
                .merge(self.world_totals_df, on=['Year'], how='left')
            )

            world_share_hs2 = (
                hs2_aggregated['World Export HS2 Total']
                / hs2_aggregated['Total World Export'].replace(0, np.nan)
            )
            hs2_aggregated['RCA_Export_2digit'] = (
                (
                    hs2_aggregated['Reporter Export HS2 Total']
                    / hs2_aggregated["Reporter's Total Export To World"].replace(0, np.nan)
                )
                / world_share_hs2
            ).fillna(0)
            hs2_aggregated['RCA_Import_2digit'] = (
                (
                    hs2_aggregated['Partner Import HS2 Total']
                    / hs2_aggregated["Partner's Total Import From World"].replace(0, np.nan)
                )
                / world_share_hs2
            ).fillna(0)
            # Unweighted RCA product (RCA_export × RCA_import). Matches the
            # per-product index published by Yang (2023) Table 3.
            hs2_aggregated['TCI_RCA_Product_2digit'] = (
                hs2_aggregated['RCA_Export_2digit'] * hs2_aggregated['RCA_Import_2digit']
            )

            hs2_aggregated = hs2_aggregated.rename(columns={
                'World Export HS2 Total': 'Total_World_Export_K',
            })
            hs2_aggregated['Total_Reporter_Export'] = (
                hs2_aggregated['Reporter Export HS2 Total'].fillna(0)
            )
            hs2_aggregated['Total_Partner_Import'] = (
                hs2_aggregated['Partner Import HS2 Total'].fillna(0)
            )

            hs2_aggregated = hs2_aggregated[[
                'Country', 'Year', 'HS2',
                'TCI_DG_2digit', 'TCI_RCA_Product_2digit',
                'RCA_Export_2digit', 'RCA_Import_2digit',
                'Total_Reporter_Export', 'Total_Partner_Import', 'Total_World_Export_K',
                'Num_Active_HS6_Pairs',
            ]]

            self.hs2_index_by_partner[partner_name] = hs2_aggregated

    def _aggregate_to_sitc(self):
        """
        SITC-section aggregation for the Yang (2023) comparison. Mirrors
        `_aggregate_hs4_to_hs2`, one classification over: HS6 rows are grouped
        to SITC section via the canonical-source SITC totals
        (`*_sitc_totals`, built from the HSSITCConcordance table).

        Form A (TCI_DG_sitc) = sum of HS6 Drysdale-Garnaut within section.
        Form C (TCI_RCA_Product_sitc) = RCA_x_section × RCA_m_section.
        """
        sitc_concordance = trade_data_loader._hs6_to_sitc_concordance()
        if sitc_concordance.empty:
            self.logger.warning("SITC aggregation skipped: HSSITCConcordance is empty.")
            return

        for partner_name, hs6_data in self.hs6_with_indicators_by_partner.items():
            # Vintage-aware: each HS6 row mapped via the concordance for the HS
            # revision active in its year — identical to the loader-side totals,
            # so numerator (DG sums) and denominator (RCA totals) sections agree.
            hs6_data = trade_data_loader._assign_sitc_section(hs6_data.copy(), sitc_concordance)

            sitc_sums = (
                hs6_data.groupby(['Country', 'Year', 'SITC'])
                .agg(
                    TCI_DG_sitc          = ('TCI_Drysdale_Garnaut', 'sum'),
                    Num_Active_HS6_Pairs = ('Active_Pair',          'sum'),
                )
                .reset_index()
            )

            partner_totals_for_partner = (
                self.partner_sitc_totals_df[self.partner_sitc_totals_df['partner'] == partner_name]
                .drop(columns=['partner'])
            )
            sitc_aggregated = (
                sitc_sums
                .merge(self.reporter_sitc_totals_df, on=['Country', 'Year', 'SITC'], how='left')
                .merge(partner_totals_for_partner,   on=['Year', 'SITC'],            how='left')
                .merge(self.world_sitc_totals_df,    on=['Year', 'SITC'],            how='left')
                .merge(self.reporter_totals_df,      on=['Country', 'Year'],         how='left')
                .merge(
                    self.partner_totals_df[self.partner_totals_df['partner'] == partner_name]
                        .drop(columns=['partner']),
                    on=['Year'], how='left',
                )
                .merge(self.world_totals_df, on=['Year'], how='left')
            )

            world_share_sitc = (
                sitc_aggregated['World Export SITC Total']
                / sitc_aggregated['Total World Export'].replace(0, np.nan)
            )
            sitc_aggregated['RCA_Export_sitc'] = (
                (
                    sitc_aggregated['Reporter Export SITC Total']
                    / sitc_aggregated["Reporter's Total Export To World"].replace(0, np.nan)
                )
                / world_share_sitc
            ).fillna(0)
            sitc_aggregated['RCA_Import_sitc'] = (
                (
                    sitc_aggregated['Partner Import SITC Total']
                    / sitc_aggregated["Partner's Total Import From World"].replace(0, np.nan)
                )
                / world_share_sitc
            ).fillna(0)
            sitc_aggregated['TCI_RCA_Product_sitc'] = (
                sitc_aggregated['RCA_Export_sitc'] * sitc_aggregated['RCA_Import_sitc']
            )

            sitc_aggregated = sitc_aggregated[[
                'Country', 'Year', 'SITC',
                'TCI_DG_sitc', 'TCI_RCA_Product_sitc',
                'RCA_Export_sitc', 'RCA_Import_sitc',
                'Num_Active_HS6_Pairs',
            ]]

            self.sitc_index_by_partner[partner_name] = sitc_aggregated

    def _calculate_headline_cij(self):
        """
        Headline Cij for each (reporter, partner, year) over the full scope.

        Two forms reported:
          Headline_Cij_DG          = Σ HS6 Drysdale-Garnaut (weighted; primary).
          Headline_Cij_RCA_Product = scope-level RCA_x × RCA_m (unweighted; the
              Yang (2023) published single-composite form, scope as one "k").
        """
        for partner_name, hs6_data in self.hs6_trade_data_by_partner.items():
            headline = (
                hs6_data.groupby(['Country', 'Year'])
                .agg(
                    Headline_Cij_DG      = ('TCI_Drysdale_Garnaut', 'sum'),
                    X_scope              = ('Reporter Export To World',  'sum'),
                    M_scope              = ('Partner Import From World', 'sum'),
                    W_scope              = ('World Export of item k',    'sum'),
                    X_total              = ("Reporter's Total Export To World",  'first'),
                    M_total              = ("Partner's Total Import From World", 'first'),
                    W_total              = ('Total World Export',                'first'),
                    Num_Active_HS6_Pairs = ('Active_Pair',          'sum'),
                )
                .reset_index()
            )
            world_share_scope = (
                headline['W_scope'] / headline['W_total'].replace(0, np.nan)
            )
            rca_x_scope = (
                (headline['X_scope'] / headline['X_total'].replace(0, np.nan)) / world_share_scope
            )
            rca_m_scope = (
                (headline['M_scope'] / headline['M_total'].replace(0, np.nan)) / world_share_scope
            )
            headline['Headline_Cij_RCA_Product'] = (rca_x_scope * rca_m_scope).fillna(0)

            headline = (
                headline[[
                    'Country', 'Year', 'Headline_Cij_DG',
                    'Headline_Cij_RCA_Product', 'Num_Active_HS6_Pairs',
                ]]
                .sort_values(['Country', 'Year'])
                .reset_index(drop=True)
            )
            self.headline_cij_by_partner[partner_name] = headline
            self.logger.info(
                "Headline Cij computed for partner %s (%d reporter-year rows).",
                partner_name, len(headline),
            )

    def _verify_partner_invariants(self, tolerance: float = 1e-9):
        """
        Pipeline-time regression guard. Raises ValueError when any of the four
        partner-side / reporter-side invariants is violated. Each invariant
        must hold by definition of Balassa RCA; a violation indicates a code
        bug that would otherwise produce silently wrong RCA values in the
        exported files.
        """
        partner_frames_hs6 = list(self.hs6_with_indicators_by_partner.items())
        partner_frames_hs4 = list(self.hs4_index_by_partner.items())
        if len(partner_frames_hs6) < 2 or len(partner_frames_hs4) < 2:
            self.logger.info("Partner-invariant check skipped: need >= 2 partner frames.")
            return

        def _raise(name: str, offending: pd.DataFrame) -> None:
            preview = offending.head(10).to_string(index=False)
            raise ValueError(
                f"Partner invariant violation: {name}\n"
                f"First {min(10, len(offending))} of {len(offending)} offending rows:\n"
                f"{preview}"
            )

        # 1. HS6 RCA Reporter Export — identical across partner frames
        # 2. HS6 TCI_Drysdale_Garnaut == TCI_RCA_DG_Decomposition (single-frame check)
        partner_a, hs6_a = partner_frames_hs6[0]
        partner_b, hs6_b = partner_frames_hs6[1]
        key_hs6 = ['Country', 'Year', 'Product code']
        joined_hs6 = (
            hs6_a[key_hs6 + ['RCA Reporter Export', 'TCI_Drysdale_Garnaut', 'TCI_RCA_DG_Decomposition']]
            .merge(
                hs6_b[key_hs6 + ['RCA Reporter Export']],
                on=key_hs6, how='inner', suffixes=(f'_{partner_a}', f'_{partner_b}'),
            )
        )
        rca_export_gap = (
            joined_hs6[f'RCA Reporter Export_{partner_a}']
            - joined_hs6[f'RCA Reporter Export_{partner_b}']
        ).abs()
        bad = joined_hs6[rca_export_gap > tolerance]
        if not bad.empty:
            _raise(f"HS6 RCA Reporter Export differs between {partner_a} and {partner_b}", bad)

        dg_decomposition_gap = (
            joined_hs6['TCI_Drysdale_Garnaut'] - joined_hs6['TCI_RCA_DG_Decomposition']
        ).abs()
        bad = joined_hs6[dg_decomposition_gap > tolerance]
        if not bad.empty:
            _raise("HS6 TCI_Drysdale_Garnaut != TCI_RCA_DG_Decomposition", bad)

        # 3. HS4 RCA_Export_4digit — identical across partner frames
        partner_a, hs4_a = partner_frames_hs4[0]
        partner_b, hs4_b = partner_frames_hs4[1]
        key_hs4 = ['Country', 'Year', 'HS4']
        joined_hs4 = hs4_a[key_hs4 + ['RCA_Export_4digit']].merge(
            hs4_b[key_hs4 + ['RCA_Export_4digit']],
            on=key_hs4, how='inner', suffixes=(f'_{partner_a}', f'_{partner_b}'),
        )
        rca4_export_gap = (
            joined_hs4[f'RCA_Export_4digit_{partner_a}']
            - joined_hs4[f'RCA_Export_4digit_{partner_b}']
        ).abs()
        bad = joined_hs4[rca4_export_gap > tolerance]
        if not bad.empty:
            _raise(f"HS4 RCA_Export_4digit differs between {partner_a} and {partner_b}", bad)

        # 4. HS4 RCA_Import_4digit — identical across reporters within each partner frame
        for partner_name, hs4_data in partner_frames_hs4:
            distinct_per_group = (
                hs4_data.groupby(['Year', 'HS4'])['RCA_Import_4digit']
                .agg(lambda s: s.max() - s.min())
            )
            bad_groups = distinct_per_group[distinct_per_group > tolerance]
            if not bad_groups.empty:
                offending = hs4_data.merge(
                    bad_groups.rename('gap').reset_index(),
                    on=['Year', 'HS4'], how='inner',
                ).sort_values(['Year', 'HS4', 'Country'])
                _raise(
                    f"HS4 RCA_Import_4digit varies across reporters for partner {partner_name}",
                    offending,
                )

        # 5–8. HS2-tier invariants — only when strategic scope has been aggregated
        if self.scope.primary_tier == 'HS2' and len(self.hs2_index_by_partner) >= 2:
            partner_frames_hs2 = list(self.hs2_index_by_partner.items())
            partner_a, hs2_a = partner_frames_hs2[0]
            partner_b, hs2_b = partner_frames_hs2[1]
            key_hs2 = ['Country', 'Year', 'HS2']

            # 5. HS2 RCA_Export_2digit — identical across partner frames
            joined_hs2 = hs2_a[key_hs2 + ['RCA_Export_2digit']].merge(
                hs2_b[key_hs2 + ['RCA_Export_2digit']],
                on=key_hs2, how='inner', suffixes=(f'_{partner_a}', f'_{partner_b}'),
            )
            rca2_export_gap = (
                joined_hs2[f'RCA_Export_2digit_{partner_a}']
                - joined_hs2[f'RCA_Export_2digit_{partner_b}']
            ).abs()
            bad = joined_hs2[rca2_export_gap > tolerance]
            if not bad.empty:
                _raise(
                    f"HS2 RCA_Export_2digit differs between {partner_a} and {partner_b}", bad,
                )

            # 6. HS2 RCA_Import_2digit — identical across reporters within each partner frame
            for partner_name, hs2_data in partner_frames_hs2:
                spread = (
                    hs2_data.groupby(['Year', 'HS2'])['RCA_Import_2digit']
                    .agg(lambda s: s.max() - s.min())
                )
                bad_groups = spread[spread > tolerance]
                if not bad_groups.empty:
                    offending = hs2_data.merge(
                        bad_groups.rename('gap').reset_index(),
                        on=['Year', 'HS2'], how='inner',
                    ).sort_values(['Year', 'HS2', 'Country'])
                    _raise(
                        f"HS2 RCA_Import_2digit varies across reporters for partner {partner_name}",
                        offending,
                    )

            # 7. Tier additivity: HS2 Cij DG == sum of HS4 Cij DG within HS2 chapter
            for partner_name, hs2_data in partner_frames_hs2:
                hs4_data = self.hs4_index_by_partner[partner_name].copy()
                hs4_data['HS2'] = hs4_data['HS4'].astype(str).str[:2]
                hs4_summed = (
                    hs4_data.groupby(['Country', 'Year', 'HS2'])['TCI_DG_4digit']
                    .sum().rename('HS4_Sum').reset_index()
                )
                joined = hs2_data[['Country', 'Year', 'HS2', 'TCI_DG_2digit']].merge(
                    hs4_summed, on=['Country', 'Year', 'HS2'], how='inner',
                )
                gap = (joined['TCI_DG_2digit'] - joined['HS4_Sum']).abs()
                bad = joined[gap > tolerance]
                if not bad.empty:
                    _raise(
                        f"HS2 Cij DG != sum of HS4 Cij within chapter for partner {partner_name}",
                        bad,
                    )

            # 8. Tier additivity: Headline Cij DG == sum of HS2 Cij DG (per Country, Year)
            for partner_name, hs2_data in partner_frames_hs2:
                headline = self.headline_cij_by_partner[partner_name]
                hs2_sum = (
                    hs2_data.groupby(['Country', 'Year'])['TCI_DG_2digit']
                    .sum().rename('HS2_Sum').reset_index()
                )
                joined = headline[['Country', 'Year', 'Headline_Cij_DG']].merge(
                    hs2_sum, on=['Country', 'Year'], how='inner',
                )
                gap = (joined['Headline_Cij_DG'] - joined['HS2_Sum']).abs()
                bad = joined[gap > tolerance]
                if not bad.empty:
                    _raise(
                        f"Headline Cij DG != sum of HS2 Cij for partner {partner_name}",
                        bad,
                    )

        check_count = 8 if self.scope.primary_tier == 'HS2' else 4
        self.logger.info(
            "Partner invariants verified: all %d checks pass.", check_count,
        )

    # ── Export ───────────────────────────────────────────────────────────────

    def _scope_export_dir(self) -> Path:
        return Path(EXPORT_DIR) / self.scope.name

    def _primary_tier_index_by_partner(self) -> dict[str, pd.DataFrame]:
        if self.scope.primary_tier == 'HS2':
            return self.hs2_index_by_partner
        if self.scope.primary_tier == 'SITC':
            return self.sitc_index_by_partner
        return self.hs4_index_by_partner

    def _export_excel(self, countries: list[str] | None, hs4_codes: list[str] | None):
        export_excel(
            self.hs4_index_by_partner,
            self.hs6_with_indicators_by_partner,
            self.headline_cij_by_partner,
            self._scope_export_dir(),
            hs2_index_by_partner=(
                self.hs2_index_by_partner if self.scope.primary_tier == 'HS2' else None
            ),
            sitc_index_by_partner=(
                self.sitc_index_by_partner if self.scope.primary_tier == 'SITC' else None
            ),
            countries=countries,
            hs4_codes=hs4_codes,
            logger=self.logger,
        )

    def _export_hs4_tci_charts(self, countries: list[str] | None, hs4_codes: list[str] | None):
        export_hs4_tci_charts(
            self._primary_tier_index_by_partner(),
            self._scope_export_dir(),
            tier_column=self.scope.primary_tier,
            countries=countries,
            tier_codes=hs4_codes,
            logger=self.logger,
        )

    def _export_word_summary(self, countries: list[str] | None, hs4_codes: list[str] | None):
        export_word_summary(
            self._primary_tier_index_by_partner(),
            self._scope_export_dir(),
            tier_column=self.scope.primary_tier,
            tier_labels=self.scope.primary_labels,
            countries=countries,
            tier_codes=hs4_codes,
            logger=self.logger,
        )

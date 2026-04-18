import numpy as np
import pandas as pd
from pathlib import Path
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DIRECTORY_FILE = f"./data/TradeMapData/data/"
EXPORT_DIR = f"./data/TradeMapData/export/"
HS_CHAPTERS_FILTER = ['84', '85', '86', '87', '88', '89', '90']
YEAR_FILTER = ['2001', '2002', '2003', '2004', '2005', '2006', '2007', '2008', '2009', '2010',
               '2011', '2012', '2013', '2014', '2015', '2016', '2017', '2018', '2019', '2020',
               '2021', '2022', '2023', '2024']

class TradeDataframeContainer:
    def __init__(self, reporter, partner, trade_type, reporter_export_to_partner, partner_import_from_world, reporter_export_to_world):
        self.reporter = reporter
        self.partner = partner
        self.trade_type = trade_type
        self.reporter_export_to_partner = reporter_export_to_partner
        self.partner_import_from_world = partner_import_from_world
        self.reporter_export_to_world = reporter_export_to_world


class TradeMapExcelData:

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.dictionary_of_trade_us: dict[str, list[TradeDataframeContainer]] = {}
        self.dictionary_of_trade_china: dict[str, list[TradeDataframeContainer]] = {}
        self.world_export: list[pd.DataFrame] = []
        self.df_final_world_export: pd.DataFrame = pd.DataFrame()
        self.trading_complimentary_index: dict[str, pd.DataFrame] = {}
        self.df_used_to_get_trading_complimentary_index: dict[str, pd.DataFrame] = {}
        self.df_4digit_index = {}
        self.df_6digit_with_weights = {}

    #---- Below I am adding methods for this class  --------

    ## This is a class I will call to process the entire stage.
    def process_calculate_trading_complimentary_index(self):
        self.load_export_data_from_txt()
        self.set_final_dataframe_for_world_export_info()
        self.process_country_data_into_one_dataframe()
        self.filter_country_final_dataframe()
        self.calculate_trading_complimentary_index()
        self.aggregate_to_4digit()
        self.sum_tci_calculation()
        self.export_complimentary_index()
        self.export_raw_data_used_for_complimentary_index()
        self.export_4digit_index()
        self.export_trial_hs4('8542')
        self.export_trial_hs4('8541')
        self.export_graph_of_tci()

    # def aggregate_to_4digit(self):
    #     for partner, hs6_group_by_4_calc_df in self.df_used_to_get_trading_complimentary_index.items():
    #         hs6_group_by_4_calc_df = hs6_group_by_4_calc_df.copy()
    #
    #         hs6_group_by_4_calc_df['HS4'] = hs6_group_by_4_calc_df['Product code'].astype(str).str[:4]
    #
    #         hs6_group_by_4_calc_df['HS4 Group Trade'] = hs6_group_by_4_calc_df.groupby(
    #             ['Country', 'Year', 'HS4']
    #         )['Reporter Export To World'].transform('sum')
    #
    #         hs6_group_by_4_calc_df['HS4 Weight'] = hs6_group_by_4_calc_df['Reporter Export To World'] / hs6_group_by_4_calc_df['HS4 Group Trade'].replace(0, np.nan)
    #
    #         hs6_group_by_4_calc_df['Cij Weighted'] = hs6_group_by_4_calc_df['HS4 Weight'] * hs6_group_by_4_calc_df['TCI_Drysdale_Garnaut']
    #         hs6_group_by_4_calc_df['TCI RCA Weighted'] = hs6_group_by_4_calc_df['HS4 Weight'] * hs6_group_by_4_calc_df['TCI Using RCA']
    #         df_4digit = (
    #             hs6_group_by_4_calc_df.groupby(['Country', 'Year', 'HS4'])
    #             .agg(
    #                 Cij_Weighted=('Cij Weighted', 'sum'),
    #                 TradeComplimentary_RCA_Weighted=('TCI RCA Weighted', 'sum'),
    #                 Total_Reporter_Export=('Reporter Export To World', 'sum'),
    #                 Total_Partner_Import=('Partner Import From World', 'sum'),
    #                 Total_World_Export_k=('World Export of item k', 'sum'),
    #                 Num_6digit_Products=('Product code', 'count'),
    #                 Xi_all_products=("Reporter's Total Export To World", 'first'),
    #                 Mj_all_products=("Partner's Total Import From World", 'first'),
    #                 WX_all_products=('Total World Export', 'first'),
    #             )
    #             .reset_index()
    #         )
    #
    #         df_4digit['RCA_Export_4digit'] = (
    #                 (df_4digit['Total_Reporter_Export'] / df_4digit['Xi_all_products'].replace(0, np.nan)) /
    #                 (df_4digit['Total_World_Export_k'] / df_4digit['WX_all_products'].replace(0, np.nan))
    #         )
    #         df_4digit['RCA_Import_4digit'] = (
    #                 (df_4digit['Total_Partner_Import'] / df_4digit['Mj_all_products'].replace(0, np.nan)) /
    #                 (df_4digit['Total_World_Export_k'] / df_4digit['WX_all_products'].replace(0, np.nan))
    #         )
    #         df_4digit['Proportion_World_Trade_4digit'] = (
    #                 df_4digit['Total_World_Export_k'] / df_4digit['WX_all_products'].replace(0, np.nan)
    #         )
    #         df_4digit['TradeComplimentary_RCA_ReCalculated'] = (
    #                 df_4digit['RCA_Export_4digit'] *
    #                 df_4digit['RCA_Import_4digit'] *
    #                 df_4digit['Proportion_World_Trade_4digit']
    #         )
    #
    #         # sanity check
    #         # assert df_4digit['Mj_all_products'].isna().sum() == 0
    #         # assert df_4digit['Xi_all_products'].isna().sum() == 0
    #         # assert df_4digit['WX_all_products'].isna().sum() == 0
    #
    #         df_4digit = df_4digit[[
    #             'Country', 'Year', 'HS4', 'Cij_Weighted', 'TradeComplimentary_RCA_Weighted', 'TradeComplimentary_RCA_ReCalculated',
    #             'RCA_Export_4digit', 'RCA_Import_4digit', 'Proportion_World_Trade_4digit',
    #             'Total_Reporter_Export', 'Total_Partner_Import', 'Total_World_Export_k', 'Num_6digit_Products'
    #         ]]
    #
    #         self.df_4digit_index[partner] = df_4digit
    #         self.df_6digit_with_weights[partner] = hs6_group_by_4_calc_df

    def aggregate_to_4digit(self):
        for partner, hs6_group_by_4_calc_df in self.df_used_to_get_trading_complimentary_index.items():
            hs6_group_by_4_calc_df = hs6_group_by_4_calc_df.copy()

            hs6_group_by_4_calc_df['HS4'] = hs6_group_by_4_calc_df['Product code'].astype(str).str[:4]

            # Count only pairs where both reporter and partner had actual trade
            # hs6_group_by_4_calc_df['Active_Pair'] = (
            #         (hs6_group_by_4_calc_df['Reporter Export To World'] > 0) &
            #         (hs6_group_by_4_calc_df['Partner Import From World'] > 0)
            # ).astype(int)

            # CORRECT - requires actual bilateral trade to have occurred
            hs6_group_by_4_calc_df['Active_Pair'] = (
                    (hs6_group_by_4_calc_df['Reporter Export To Partner'] > 0) &
                    (hs6_group_by_4_calc_df['Partner Import From World'] > 0)
            ).astype(int)

            active_group_trade = hs6_group_by_4_calc_df.loc[
                hs6_group_by_4_calc_df['Active_Pair'] == 1
            ].groupby(['Country', 'Year', 'HS4'])['Reporter Export To World'].transform('sum')

            hs6_group_by_4_calc_df['HS4 Group Trade'] = active_group_trade

            hs6_group_by_4_calc_df['HS4 Weight'] = np.where(
                    hs6_group_by_4_calc_df['Active_Pair'] == 1,
                    hs6_group_by_4_calc_df['Reporter Export To World'] /
                    hs6_group_by_4_calc_df['HS4 Group Trade'].replace(0, np.nan),
                    0
            )

            hs6_group_by_4_calc_df['Cij Weighted'] = (
                    hs6_group_by_4_calc_df['HS4 Weight'] *
                    hs6_group_by_4_calc_df['TCI_Drysdale_Garnaut']
            )
            hs6_group_by_4_calc_df['TCI RCA Weighted'] = (
                    hs6_group_by_4_calc_df['HS4 Weight'] *
                    hs6_group_by_4_calc_df['TCI Using RCA']
            )

            df_4digit = (
                hs6_group_by_4_calc_df.groupby(['Country', 'Year', 'HS4'])
                .agg(
                    Cij_Weighted=('Cij Weighted', 'sum'),
                    TradeComplimentary_RCA_Weighted=('TCI RCA Weighted', 'sum'),
                    Total_Reporter_Export=('Reporter Export To World', 'sum'),
                    Total_Partner_Import=('Partner Import From World', 'sum'),
                    Total_World_Export_k=('World Export of item k', 'sum'),
                    Num_6digit_Products=('Active_Pair', 'sum'),  # active bilateral pairs only
                    Xi_all_products=("Reporter's Total Export To World", 'first'),
                    Mj_all_products=("Partner's Total Import From World", 'first'),
                    WX_all_products=('Total World Export', 'first'),
                )
                .reset_index()
            )

            df_4digit['RCA_Export_4digit'] = (
                    (df_4digit['Total_Reporter_Export'] / df_4digit['Xi_all_products'].replace(0, np.nan)) /
                    (df_4digit['Total_World_Export_k'] / df_4digit['WX_all_products'].replace(0, np.nan))
            )
            df_4digit['RCA_Import_4digit'] = (
                    (df_4digit['Total_Partner_Import'] / df_4digit['Mj_all_products'].replace(0, np.nan)) /
                    (df_4digit['Total_World_Export_k'] / df_4digit['WX_all_products'].replace(0, np.nan))
            )
            df_4digit['Proportion_World_Trade_4digit'] = (
                    df_4digit['Total_World_Export_k'] / df_4digit['WX_all_products'].replace(0, np.nan)
            )
            df_4digit['TradeComplimentary_RCA_ReCalculated'] = (
                    df_4digit['RCA_Export_4digit'] *
                    df_4digit['RCA_Import_4digit'] *
                    df_4digit['Proportion_World_Trade_4digit']
            )

            zero_active = df_4digit['Num_6digit_Products'] == 0
            if zero_active.any():
                invalid_zero_active = df_4digit.loc[zero_active & (
                    (df_4digit['Cij_Weighted'].abs() > 0) |
                    (df_4digit['TradeComplimentary_RCA_Weighted'].abs() > 0) |
                    (df_4digit['TradeComplimentary_RCA_ReCalculated'].abs() > 0)
                )]
                if not invalid_zero_active.empty:
                    self.logger.warning(
                        "Zero-active 4-digit groups with nonzero weighted values detected for partner %s:\n%s",
                        partner,
                        invalid_zero_active[['Country', 'Year', 'HS4', 'Cij_Weighted', 'TradeComplimentary_RCA_Weighted', 'TradeComplimentary_RCA_ReCalculated']]
                    )
                df_4digit.loc[zero_active, [
                    'Cij_Weighted', 'TradeComplimentary_RCA_Weighted', 'TradeComplimentary_RCA_ReCalculated'
                ]] = 0

            df_4digit = df_4digit[[
                'Country', 'Year', 'HS4', 'Cij_Weighted', 'TradeComplimentary_RCA_Weighted',
                'TradeComplimentary_RCA_ReCalculated', 'RCA_Export_4digit', 'RCA_Import_4digit',
                'Proportion_World_Trade_4digit', 'Total_Reporter_Export', 'Total_Partner_Import',
                'Total_World_Export_k', 'Num_6digit_Products'
            ]]

            self.df_4digit_index[partner] = df_4digit
            self.df_6digit_with_weights[partner] = hs6_group_by_4_calc_df

    def export_4digit_index(self):
        export_dir = Path(EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        for partner, df in self.df_4digit_index.items():
            df.to_csv(Path(export_dir, f"{partner}_4digit_index.csv"))

    def export_trial_hs4(self, hs4_code: str):
        export_dir = Path(EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)

        for partner, df in self.df_6digit_with_weights.items():
            # File 1: 6-digit detail — already has weights from aggregate_to_4digit
            df_6digit = df[df['HS4'] == hs4_code].copy()
            df_6digit.to_csv(Path(export_dir, f"{partner}_{hs4_code}_6digit_detail.csv"), index=False)

            # File 2: 4-digit summary
            if partner in self.df_4digit_index:
                df_4digit = self.df_4digit_index[partner]
                df_4digit[df_4digit['HS4'] == hs4_code].to_csv(
                    Path(export_dir, f"{partner}_{hs4_code}_4digit_summary.csv"), index=False
                )

    def filter_country_final_dataframe(self):
        for key, value in self.df_used_to_get_trading_complimentary_index.items():
            filtered_dataframe = self.filter_by_chapter(value)
            filtered_dataframe = self.filter_by_year(filtered_dataframe)
            self.df_used_to_get_trading_complimentary_index[key] = filtered_dataframe


    def filter_by_chapter(self, dataframe: pd.DataFrame):
        dataframe = dataframe[
            dataframe['Product code'].astype(str).str[:2].str.upper().isin(HS_CHAPTERS_FILTER) |
            (dataframe['Product code'].astype(str).str.upper() == 'TOTAL')
            ]
        return dataframe

    def filter_by_year(self, dataframe: pd.DataFrame):
        dataframe = dataframe[
            dataframe['Year'].astype(str).isin(YEAR_FILTER)
        ]
        return dataframe

    def process_country_data_into_one_dataframe(self):
        self.process_country_data(self.dictionary_of_trade_china, "China")
        self.process_country_data(self.dictionary_of_trade_us, "US")
        
    def export_graph_of_tci(self):
        export_dir = Path(EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)

        for partner, df in self.trading_complimentary_index.items():
            if df.empty:
                continue

            # Prepare data for plotting
            df_plot = df.copy()
            # Convert Year to numeric to ensure correct ordering and spacing on x-axis

            df_plot['Year'] = pd.to_numeric(df_plot['Year'], errors='coerce')
            df_plot = df_plot.dropna(subset=['Year'])
            df_plot = df_plot.sort_values('Year')
            df_plot = df_plot.dropna(subset=['TCI_Drysdale_Garnaut', 'TCI Using RCA'])

            # Plot TCI_Drysdale_Garnaut
            plt.figure(figsize=(12, 8))
            for country in df_plot['Country'].unique():
                country_data = df_plot[df_plot['Country'] == country]
                plt.plot(country_data['Year'], country_data['TCI_Drysdale_Garnaut'], marker='o', label=country)

            plt.title(f'Trade Complementarity Index (Drysdale & Garnaut) - {partner}')
            plt.xlabel('Year')
            plt.ylabel('TCI')
            plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(export_dir / f"{partner}_TCI_Drysdale_Garnaut.png")
            plt.close()

            # Plot TCI Using RCA
            plt.figure(figsize=(12, 8))
            for country in df_plot['Country'].unique():
                country_data = df_plot[df_plot['Country'] == country]
                plt.plot(country_data['Year'], country_data['TCI Using RCA'], marker='o', label=country)

            plt.title(f'Trade Complementarity Index (RCA) - {partner}')
            plt.xlabel('Year')
            plt.ylabel('TCI')
            plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(export_dir / f"{partner}_TCI_RCA.png")
            plt.close()

        self.logger.info("TCI graphs exported successfully.")

    def export_raw_data_used_for_complimentary_index(self):
        export_dir = Path(EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)

        for country, df in self.df_used_to_get_trading_complimentary_index.items():
            move_to = Path(export_dir, f"{country}_raw_data.csv")
            df.to_csv(move_to)

    def export_complimentary_index(self):
        export_dir = Path(EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)

        for country, df in self.trading_complimentary_index.items():
            move_to = Path(export_dir, f"{country}_TCI.csv")
            df.to_csv(move_to)

    #--------------set_final_dataframe_for_world_export_info is called so we have a dataframe for world export value created
    #--------------This will have the calculated and provided total world export along with each item exports.
    def set_final_dataframe_for_world_export_info(self):
        if self.world_export:
            df_world_export = TradeMapExcelData.process_dataframe_list_through_melting(self.world_export, "Year",
                                                                                       "Value", [0, 1])
            df_world_export.rename(columns={"Value": "World Export of item k"}, inplace=True)
            total_exports = df_world_export[df_world_export['Product code'].astype(str).str.upper() == "TOTAL"].set_index("Year")["World Export of item k"]
            df_world_export['Total World Export'] = df_world_export['Year'].map(total_exports)
            df_world_export = df_world_export[df_world_export['Product code'].astype(str).str.upper() != "TOTAL"]
            df_world_export['Calculated Total World Export'] = df_world_export.groupby("Year")["World Export of item k"].transform("sum")
            df_world_export["Total World Export Diff"] = df_world_export["Calculated Total World Export"] - df_world_export["Total World Export"]
            self.df_final_world_export = df_world_export
        else:
            logging.error("missing world_export")

    def calculate_trading_complimentary_index(self):
        #----------------------------WE WILL CALCULATE EACH NOW---------------------------
        self.calculate_tci()
        self.calculate_rca()
        #-------------------------------------------------------------------------------------------------

    def process_country_data(self, dictionary_of_exports_to_partner, partner):
        df_reporter_export_to_partner, df_reporter_export_to_world, df_partner_import_from_world = (
            TradeMapExcelData.process_dataframe_list_for_countries(dictionary_of_exports_to_partner)
        )

        df_reporter_all = pd.merge(
            df_reporter_export_to_partner,
            df_reporter_export_to_world,
            on=["Country", "Year", "Product code"], how="outer"
        )

        df_reporter_all = pd.merge(
            df_reporter_all,
            df_partner_import_from_world,
            on=["Country", "Year", "Product code"], how="outer"
        )

        cols_to_fill = ['Reporter Export To Partner', 'Reporter Export To World', 'Partner Import From World']
        df_reporter_all[cols_to_fill] = df_reporter_all[cols_to_fill].fillna(0)

        columns_to_get_for_total_values = ["Year", "Country", 'Reporter Export To Partner', 'Reporter Export To World', 'Partner Import From World']
        rename = {
            'Reporter Export To Partner': "Reporter's Total Export To Partner",
            'Reporter Export To World': "Reporter's Total Export To World",
            'Partner Import From World': "Partner's Total Import From World"
        }
        df_countries_total_trade_value = (
            df_reporter_all[df_reporter_all["Product code"].str.lower() == "total"][columns_to_get_for_total_values].copy()
        )
        df_countries_total_trade_value.rename(columns=rename, inplace=True)
        df_reporter_all = df_reporter_all.merge(df_countries_total_trade_value, on=["Year", "Country"], how="left")

        df_reporter_all = pd.merge(df_reporter_all, self.df_final_world_export, on=["Year", "Product code"], how="left")

        # Filter out 'TOTAL' from the merged dataframes before calculating sums
        df_reporter_all = df_reporter_all[df_reporter_all['Product code'].astype(str).str.upper() != 'TOTAL']

        df_reporter_all["Calculated Reporter's Total Export To Partner"] = (
            df_reporter_all.groupby(["Year", "Country"])["Reporter Export To Partner"].transform("sum")
        )
        df_reporter_all["Calculated Reporter's Total Export To World"] = (
            df_reporter_all.groupby(["Year", "Country"])["Reporter Export To World"].transform("sum")
        )
        df_reporter_all["Calculated Partner's Total Import From World"] = (
            df_reporter_all.groupby(["Year", "Country"])["Partner Import From World"].transform("sum")
        )

        df_reporter_all["Reporter's Total Export To Partner Diff"] = (
            df_reporter_all["Calculated Reporter's Total Export To Partner"] - df_reporter_all["Reporter's Total Export To Partner"]
        )
        df_reporter_all["Reporter's Total Export To World Diff"] = (
                df_reporter_all["Calculated Reporter's Total Export To World"] - df_reporter_all["Reporter's Total Export To World"]
        )
        df_reporter_all["Partner's Total Import From World Diff"] = (
                df_reporter_all["Calculated Partner's Total Import From World"] - df_reporter_all["Partner's Total Import From World"]
        )

        df_reporter_all = df_reporter_all[[
            'Country', 'Year', 'Product code', 'Product label',
            'Reporter Export To Partner', 'Reporter Export To World',
            'Partner Import From World', 'World Export of item k', 'Total World Export',
            'Calculated Total World Export', 'Total World Export Diff',
            "Reporter's Total Export To Partner", "Calculated Reporter's Total Export To Partner", "Reporter's Total Export To Partner Diff",
            "Reporter's Total Export To World", "Calculated Reporter's Total Export To World", "Reporter's Total Export To World Diff",
            "Partner's Total Import From World", "Calculated Partner's Total Import From World", "Partner's Total Import From World Diff"
        ]]

        df_reporter_all.sort_values(by=['Product code', 'Year'], ascending=[True, False], inplace=True,
                                    ignore_index=True)

        df_reporter_all["Reporter's Total Export To World"] = df_reporter_all[
            "Reporter's Total Export To World"].fillna(df_reporter_all["Calculated Reporter's Total Export To World"])
        df_reporter_all["Partner's Total Import From World"] = df_reporter_all[
            "Partner's Total Import From World"].fillna(df_reporter_all["Calculated Partner's Total Import From World"])

        self.df_used_to_get_trading_complimentary_index[partner] = df_reporter_all
        self.logger.info("dataframe form for calculation completed successfully.")

    def sum_tci_calculation(self):
        for partner, df_report_all in self.df_used_to_get_trading_complimentary_index.items():
            df_tci = (df_report_all.groupby(["Country", "Year"])[["TCI_Drysdale_Garnaut", "TCI Using RCA"]]
                                                         .sum().reset_index())
            df_tci["Diff in calculations"] = df_tci["TCI_Drysdale_Garnaut"] - df_tci["TCI Using RCA"]
            self.trading_complimentary_index[partner] = df_tci

    def calculate_tci(self):
        for partner, df_report_all in self.df_used_to_get_trading_complimentary_index.items():
            df_report_all["TCI_Drysdale_Garnaut"] = (
                    (df_report_all["Reporter Export To World"] / df_report_all[
                        "Reporter's Total Export To World"].replace(0, np.nan)) *
                    (df_report_all["Partner Import From World"] / df_report_all[
                        "Partner's Total Import From World"].replace(0, np.nan)) *
                    (df_report_all["Total World Export"] / df_report_all["World Export of item k"].replace(0,np.nan))
            ).fillna(0)

            self.df_used_to_get_trading_complimentary_index[partner] = df_report_all
            self.logger.info("Trade Complementarity Index calculated successfully.")

    def calculate_rca(self):
        for partner, df_report_all in self.df_used_to_get_trading_complimentary_index.items():
            df_report_all["RCA Reporter Export"] = (
                    (df_report_all["Reporter Export To World"] / df_report_all["Reporter's Total Export To World"].replace(0, np.nan)) /
                    (df_report_all["World Export of item k"] / df_report_all["Total World Export"].replace(0,np.nan))
                    .replace(0, np.nan)
            ).fillna(0)

            df_report_all["RCA Partner Import"] = (
                    (df_report_all["Partner Import From World"] / df_report_all["Partner's Total Import From World"].replace(0, np.nan)) /
                    (df_report_all["World Export of item k"] / df_report_all["Total World Export"].replace(0,np.nan)).replace(0, np.nan)
            ).fillna(0)

            df_report_all["Proportion World Trade"] = (
                (df_report_all["World Export of item k"] / df_report_all["Total World Export"]).replace(0,np.nan)
            ).fillna(0)

            df_report_all["TCI Using RCA"] = (
                    df_report_all["RCA Reporter Export"] *
                    df_report_all["RCA Partner Import"] *
                    df_report_all["Proportion World Trade"]
            )

            self.df_used_to_get_trading_complimentary_index[partner] = df_report_all

        self.logger.info("Revealed Comparative Advantage calculated successfully.")

    @staticmethod
    def process_dataframe_list_for_countries(dictionary_of_trades: dict[str, list[TradeDataframeContainer]]):
        df_reporter_export_to_partner = pd.DataFrame()
        df_reporter_export_to_world = pd.DataFrame()
        df_partner_import_from_world = pd.DataFrame()

        # Using the dictionary of trades where key is partner and value is  list of calculated TradeDataframeContainer. We
        # then use process_dataframe_list to merge the years together.
        for reporter, list_of_trades in dictionary_of_trades.items():

            df_reporter_export_to_partner_curr = TradeMapExcelData.process_dataframe_list_through_melting(
                [trade.reporter_export_to_partner for trade in list_of_trades],
                "Year",
                "Value",
                [0]
            )
            df_reporter_export_to_partner_curr["Country"] = reporter
            df_reporter_export_to_partner = pd.concat([df_reporter_export_to_partner, df_reporter_export_to_partner_curr], ignore_index=True)

            df_reporter_export_to_world_curr = TradeMapExcelData.process_dataframe_list_through_melting(
                [trade.reporter_export_to_world for trade in list_of_trades],
                "Year",
                "Value",
                [0]
            )
            df_reporter_export_to_world_curr["Country"] = reporter
            df_reporter_export_to_world = pd.concat([df_reporter_export_to_world, df_reporter_export_to_world_curr], ignore_index=True)

            df_partner_import_from_world_curr = TradeMapExcelData.process_dataframe_list_through_melting(
                [trade.partner_import_from_world for trade in list_of_trades],
                "Year",
                "Value",
                [0]
            )
            df_partner_import_from_world_curr["Country"] = reporter
            df_partner_import_from_world = pd.concat([df_partner_import_from_world, df_partner_import_from_world_curr], ignore_index=True)

        df_reporter_export_to_partner.rename(columns={"Value":"Reporter Export To Partner"}, inplace=True)
        df_reporter_export_to_world.rename(columns={"Value":"Reporter Export To World"}, inplace=True)
        df_partner_import_from_world.rename(columns={"Value":"Partner Import From World"}, inplace=True)

        return df_reporter_export_to_partner, df_reporter_export_to_world, df_partner_import_from_world

    #----------------The code below lookat the list of dataframes, then using the first column as index, will concat the list of tables together
    # Then we remove the dup columns and drop columns with all NAs. Using the id_indices, we then melt all the other columns to be in row
    # with the column name values_to_melt. The value seen in each cell will be in column value_name.

    @staticmethod
    def process_dataframe_list_through_melting(list_of_dataframes: list, value_to_melt: str, value_name: str, id_indices: list[int]):
        indexed_df = [df.set_index(df.columns[0]) for df in list_of_dataframes]
        df = pd.concat(indexed_df, axis=1)
        df = df.reset_index()
        df = df.loc[:, ~df.columns.duplicated()]
        df = df.dropna(axis=1, how="all")

        id_vars_names = [df.columns[i] for i in id_indices]
        df = df.melt(id_vars=id_vars_names, var_name=value_to_melt, value_name=value_name)
        df = df.sort_values(by=[df.columns[0], 'Year'], ascending= [False, True])
        return df


    def load_export_data_from_txt(self):
        file_path = Path(DIRECTORY_FILE)
        self.extract_txt_content(file_path)

    #----------------This function is used by me to extract the contents from .txt file I downloaded from Trade Map----------
    def extract_txt_content(self, file_path):
        file_path = Path(file_path)

        if file_path.exists():

            for curr_file_path in file_path.iterdir():
                if curr_file_path.is_file() and curr_file_path.suffix in ['.txt']:
                    try:

                        if "world" in str(curr_file_path).lower():
                            new_columns = {}
                            trade_df = pd.read_csv(curr_file_path, sep='\t')
                            for col in trade_df.columns:
                                if "value in" in col.lower():

                                    year = col.lower().split("value in")[-1].split(",")[0].strip()
                                    new_columns[col] = year
                                else:
                                    new_columns[col] = col
                            trade_df.rename(columns=new_columns, inplace=True)

                            self.world_export.append(trade_df)


                        else:
                            reporter = curr_file_path.stem.split("_")[0]
                            partner = curr_file_path.stem.split("_")[1]
                            trade_df = pd.read_csv(curr_file_path, sep='\t')

                            hs_id = trade_df.columns[0]
                            reporter_export_to_partner = [col for col in trade_df.columns if "exports to" in col.lower() and "world" not in col.lower()]
                            partner_import_from_world = [col for col in trade_df.columns if "imports from world" in col.lower()]
                            reporter_export_to_world = [col for col in trade_df.columns if "exports to world" in col.lower()]

                            df_reporter_export_to_partner= TradeMapExcelData.get_only_year_value("exports to", trade_df[[hs_id] + reporter_export_to_partner].copy()).dropna(axis=1, how="all")
                            df_partner_import_from_world = TradeMapExcelData.get_only_year_value("imports from world", trade_df[[hs_id] + partner_import_from_world].copy()).dropna(axis=1, how="all")
                            df_reporter_export_to_world = TradeMapExcelData.get_only_year_value("exports to world", trade_df[[hs_id] + reporter_export_to_world].copy()).dropna(axis=1, how="all")

                            trade_container = TradeDataframeContainer(
                                reporter, partner, "export",
                                reporter_export_to_partner = df_reporter_export_to_partner,
                                reporter_export_to_world = df_reporter_export_to_world,
                                partner_import_from_world = df_partner_import_from_world
                            )

                            if partner.lower() == "china":
                                if self.dictionary_of_trade_china.get(reporter) is None:
                                    self.dictionary_of_trade_china[reporter] = list()

                                self.dictionary_of_trade_china[reporter].append(trade_container)

                            if partner.lower() == "us":
                                if self.dictionary_of_trade_us.get(reporter) is None:
                                    self.dictionary_of_trade_us[reporter] = list()

                                self.dictionary_of_trade_us[reporter].append(trade_container)

                        self.logger.info(f"Processed and archived: {curr_file_path.name}")

                    except Exception as e:
                        print(f"Error reading file {curr_file_path}: {e}")
                else:
                    self.logger.warning(f"File {curr_file_path} skipped")

    @staticmethod
    def get_only_year_value(value_to_replace, dataframe: pd.DataFrame) -> pd.DataFrame:
        new_names = {}
        for col in dataframe.columns:
            if value_to_replace in col:
                # Added .split(",")[0] to ensure we drop the ", USD" part
                year = col.split("Value in ")[-1].split(",")[0].strip()
                new_names[col] = year
        return dataframe.rename(columns=new_names)
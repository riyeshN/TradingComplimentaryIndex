import comtradeapicall
import pandas as pd
import logging, os
from pathlib import Path
import time

API_KEY = "3e150b5d6beb4b78bacc2f579a611171"
BASE_DIRECTORY = "./data/"
REF_DIRECTORY = "reference_data/"
REF_FILE_NAME = f"country_code_reference_data{time.strftime('%Y%m%d')}.csv"
TRADE_DIRECTORY = "trade_data/"
TRADE_FILE_NAME = f"trade_data{time.strftime('%Y%m%d')}.csv"

class ComtradeReferenceData:
    def __init__(self):
        self.export_location = BASE_DIRECTORY + REF_DIRECTORY
        self.export_file_name = REF_FILE_NAME
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_updated_reference_data_for_country_name(self):
        self.logger.info("Getting updated reference data.")

        df_reporters = comtradeapicall.getReference("reporter")
        df_reporters = df_reporters[["reporterCode", "text", "reporterCodeIsoAlpha2"]].rename(
            columns = {"reporterCode": "Code",
                       "reporterCodeIsoAlpha2": "IsoAlpha2"})

        df_partners = comtradeapicall.getReference("partner")
        df_partners = df_partners[["PartnerCode", "text", "PartnerCodeIsoAlpha2"]].rename(
            columns={"PartnerCode": "Code",
                     "PartnerCodeIsoAlpha2": "IsoAlpha2"}
        )

        df_unique = pd.concat([df_reporters, df_partners], ignore_index=True).drop_duplicates(subset=['Code']).sort_values(by="Code")

        normalized_path = Path(self.export_location + self.export_file_name)
        normalized_path.parent.mkdir(parents=True, exist_ok=True)

        df_unique.to_csv(normalized_path, index=False)

class ComtradeTradeData:

    def __init__(self, reporter: list, partner: list, trade_type: str, frequency: str,
                 year_period: list, cmd_code: str, flow_code: str):

        self.export_location = BASE_DIRECTORY + TRADE_DIRECTORY
        self.export_file_name = TRADE_FILE_NAME
        self.logger = logging.getLogger(self.__class__.__name__)
        self.map_of_country_codes = self.get_country_code_list()
        self.reporter = reporter
        self.partner = partner
        self.trade_type = trade_type
        self.frequency = frequency
        self.year_period = year_period
        self.cmd_code = cmd_code
        self.flow_code = flow_code

    def fetch_trade_data(self):
        reporter_codes = [(x, self.map_of_country_codes.get(x)) for x in self.reporter]
        partner_codes = [self.map_of_country_codes.get(x) for x in self.partner]

        reporter_codes = [(iso, code) for iso, code in reporter_codes if code is not None]
        partner_codes = [x for x in partner_codes if x is not None]

        if not reporter_codes or not partner_codes:
            self.logger.error("Missing country codes")
            return

        for year in self.year_period:
            for reporter_iso, reporter_id in reporter_codes:
                self.logger.info(f"Fetching data for YEAR: {year} --- Reporter: {reporter_iso} ({reporter_id})")

                try:
                    trade_df = comtradeapicall.getFinalData(
                        subscription_key=API_KEY,
                        typeCode=self.trade_type,         
                        freqCode=self.frequency,          
                        clCode="HS",           
                        period=str(year),      
                        reporterCode=reporter_id,
                        cmdCode=self.cmd_code,         
                        flowCode=self.flow_code,          
                        partnerCode=','.join(map(str, partner_codes)),
                        partner2Code=None,
                        customsCode=None,
                        motCode=None,
                        format_output='JSON',
                        aggregateBy=None,
                        breakdownMode='classic',
                        includeDesc=True       
                    )
                    if trade_df is None or trade_df.empty:
                        self.logger.error(f"No data found for YEAR: {year} --- Reporter: {reporter_iso}")
                    
                    normalized_export_path = Path(f"{self.export_location}{year}_{reporter_iso}_{self.export_file_name}")
                    
                    normalized_export_path.parent.mkdir(parents=True, exist_ok=True)
                    trade_df.to_csv(normalized_export_path, index=False)

                except Exception as e:
                    self.logger.error(f"Error fetching data for YEAR: {year} --- Reporter: {reporter_iso} --- Error: {e}")

    def get_country_code_list(self):
        comtrade_ref = ComtradeReferenceData()
        path_to_check = Path(comtrade_ref.export_location + comtrade_ref.export_file_name)

        if not path_to_check.exists():
            comtrade_ref.get_updated_reference_data_for_country_name()

        df_country_code = pd.read_csv(comtrade_ref.export_location + comtrade_ref.export_file_name)
        return df_country_code.set_index("IsoAlpha2")["Code"].to_dict()

import comtradeapicall
import pandas as pd
from pathlib import Path
from django.test import TestCase
from loadFiles.models import CountryExportToWorld, PartnerImportFromWorld
from loadFiles.services.ComtradeDownload import ComtradeReferenceData

MATCH_TOLERANCE = 0.05       # 5% — acceptable difference between DB and Comtrade
MIN_MATCH_RATE = 0.93        # 93% of compared rows must be within tolerance

COMTRADE_API_ROW_LIMIT = 500  # Free API cap


class ComtradeDataIntegrityTest(TestCase):
    """
    Validates that trade values in the database match UN Comtrade API values.
    Fetches up to 500 rows from the free Comtrade preview API and compares
    against the corresponding DB table on a product-by-product basis.
    A match rate below 93% within 5% tolerance fails the test.
    """

    def _get_comtrade_code(self, iso2: str) -> int:
        ref_dir = Path(ComtradeReferenceData().export_location)
        csv_files = sorted(ref_dir.glob("country_code_reference_data*.csv"), reverse=True)
        self.assertTrue(csv_files, "No country code reference CSV found. Run update_reference_for_country_id first.")
        df = pd.read_csv(csv_files[0])
        matches = df[df["IsoAlpha2"].str.upper() == iso2.upper()]
        # Prefer current country over historical entries (historical names contain year ranges)
        current = matches[~matches["text"].str.contains(r"\(.*\d{4}", regex=True, na=False)]
        best = current if not current.empty else matches
        return int(best.iloc[0]["Code"])

    def _fetch_comtrade(self, country_code: int, year: int, flow: str) -> pd.DataFrame:
        result = comtradeapicall.previewFinalData(
            typeCode="C", freqCode="A", clCode="HS",
            period=str(year), reporterCode=country_code,
            cmdCode="AG6", flowCode=flow, partnerCode="0",
            partner2Code=None, customsCode=None, motCode=None,
            format_output="JSON", aggregateBy=None, breakdownMode="classic", includeDesc=False,
        )
        return result if result is not None else pd.DataFrame()

    def _assert_match_rate(self, db_name: str, year: int, flow: str, comtrade_code: int):
        comtrade_df = self._fetch_comtrade(comtrade_code, year, flow)
        self.assertFalse(comtrade_df.empty, f"Comtrade returned no data for code {comtrade_code}, year {year}, flow {flow}.")

        comtrade_df = (
            comtrade_df
            .rename(columns={"cmdCode": "product_code", "primaryValue": "comtrade_value_usd"})
            .assign(product_code=lambda d: d["product_code"].astype(str).str.strip())
            [["product_code", "comtrade_value_usd"]]
            .dropna(subset=["comtrade_value_usd"])
        )
        comtrade_df["comtrade_value_thousands"] = comtrade_df["comtrade_value_usd"] / 1000

        model = CountryExportToWorld if flow == "X" else PartnerImportFromWorld
        filter_kwargs = {"reporter": db_name, "year": str(year)} if flow == "X" else {"partner": db_name, "year": str(year)}
        db_records = list(model.objects.filter(**filter_kwargs).values("product_code", "value_usd_thousands"))
        self.assertTrue(db_records, f"No DB records for {db_name}, year {year}, flow {flow}.")

        db_df = (
            pd.DataFrame(db_records)
            .assign(product_code=lambda d: d["product_code"].astype(str).str.strip())
            .rename(columns={"value_usd_thousands": "db_value"})
        )

        both = pd.merge(comtrade_df, db_df, on="product_code", how="inner")
        self.assertGreater(len(both), 0, "No matching product codes between Comtrade and DB.")

        both["pct_diff"] = (
            (both["comtrade_value_thousands"] - both["db_value"]).abs()
            / both["comtrade_value_thousands"].replace(0, float("nan"))
        )
        match_rate = (both["pct_diff"] <= MATCH_TOLERANCE).sum() / len(both)

        self.assertGreaterEqual(
            match_rate, MIN_MATCH_RATE,
            f"{db_name} {year} flow={flow}: match rate {match_rate:.1%} is below {MIN_MATCH_RATE:.0%} threshold. "
            f"Compared {len(both)} products (Comtrade cap: {COMTRADE_API_ROW_LIMIT} rows)."
        )

    def test_vietnam_exports_to_world_2022(self):
        self._assert_match_rate("Vietnam", 2022, "X", comtrade_code=704)

    def test_china_imports_from_world_2022(self):
        self._assert_match_rate("China", 2022, "M", comtrade_code=156)

    def test_us_imports_from_world_2022(self):
        self._assert_match_rate("US", 2022, "M", comtrade_code=842)

import pandas as pd
from pathlib import Path
from django.test import TestCase
from loadFiles.services.TCICalculator import TCICalculator

MIN_RCA_CORRELATION = 0.98   # Pearson correlation threshold for RCA formula validation


class RCAFormulaValidationTest(TestCase):
    """
    Validates the Balassa (1965) RCA formula against World Bank WITS scores.
    Reads a WITS-exported CSV from data/reference_data/, runs the TCI pipeline
    up to the RCA calculation step, and compares on matching HS6 product codes.
    A Pearson correlation below 0.98 fails the test.

    WITS CSV download: wits.worldbank.org → Advanced Query → Trade Outcomes Indicators
    → Indicator: Revealed Comparative Advantage → Reporter, Year, All Products → Submit.
    Place downloaded CSV in data/reference_data/.
    """

    WITS_DIR = Path("data/reference_data")

    def _load_pipeline_rca(self, db_reporter: str, year: int) -> pd.DataFrame:
        calculator = TCICalculator()
        calculator._load_from_db()
        calculator._filter_by_hs_chapter_and_year()
        calculator._calculate_tci_drysdale_garnaut()
        calculator._calculate_rca_and_tci_rca()

        partner_key = next(iter(calculator.hs6_trade_data_by_partner))
        hs6_data = calculator.hs6_trade_data_by_partner[partner_key]
        return (
            hs6_data[
                (hs6_data["Country"] == db_reporter)
                & (hs6_data["Year"] == str(year))
            ]
            [["Product code", "RCA Reporter Export"]]
            .rename(columns={"Product code": "product_code", "RCA Reporter Export": "our_rca"})
            .copy()
        )

    def _load_wits_rca(self, csv_path: Path, wits_reporter: str, year: int) -> pd.DataFrame:
        raw = pd.read_csv(csv_path, dtype=str)
        raw.columns = raw.columns.str.strip().str.lower()
        filtered = raw[
            raw["reportername"].str.strip().str.lower().str.contains(wits_reporter.lower(), na=False)
            & (raw["year"].str.strip() == str(year))
            & (raw["partneriso3"].str.strip().str.upper() == "WLD")
        ].copy()
        filtered["product_code"] = filtered["productcode"].str.strip().str.zfill(6)
        filtered["wits_rca"] = pd.to_numeric(filtered["reavealed comparative advantage"], errors="coerce")
        return filtered[["product_code", "wits_rca"]].dropna(subset=["wits_rca"])

    def _assert_rca_correlation(self, db_reporter: str, wits_reporter: str, year: int, csv_path: Path):
        self.assertTrue(csv_path.exists(), f"WITS CSV not found: {csv_path}")

        our_rca = self._load_pipeline_rca(db_reporter, year)
        self.assertFalse(our_rca.empty, f"No pipeline RCA data for reporter='{db_reporter}', year={year}.")

        wits_rca = self._load_wits_rca(csv_path, wits_reporter, year)
        self.assertFalse(wits_rca.empty, f"No WITS RCA data for reporter='{wits_reporter}', year={year}.")

        both = pd.merge(our_rca, wits_rca, on="product_code", how="inner")
        self.assertGreater(len(both), 0, "No matching HS6 product codes between pipeline and WITS.")

        correlation = both["our_rca"].corr(both["wits_rca"])
        self.assertGreaterEqual(
            correlation, MIN_RCA_CORRELATION,
            f"{db_reporter} {year}: Pearson correlation {correlation:.4f} is below {MIN_RCA_CORRELATION} threshold. "
            f"Compared {len(both)} HS6 products."
        )

    def test_korea_rca_hs8542_2022(self):
        csv_path = self.WITS_DIR / "DataJobID-3071537_3071537_allItems.csv"
        self._assert_rca_correlation("KoreaRepublic", "Korea, Rep.", 2022, csv_path)

    def test_japan_rca_hs8542_2022(self):
        csv_path = self.WITS_DIR / "DataJobID-3071538_3071538_japan8542.csv"
        self._assert_rca_correlation("Japan", "Japan", 2022, csv_path)

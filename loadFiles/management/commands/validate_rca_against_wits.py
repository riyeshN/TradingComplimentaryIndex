import pandas as pd
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from loadFiles.services.TCICalculator import TCICalculator

TOP_DISCREPANCY_DISPLAY = 20


class Command(BaseCommand):
    help = (
        "Compare our computed HS6-level RCA Reporter Export against World Bank WITS Balassa RCA scores. "
        "Download WITS data from https://wits.worldbank.org/ -> Trade Outcomes -> Export Competitiveness Map."
    )

    def add_arguments(self, parser):
        parser.add_argument("--wits_csv", required=True, help="Path to downloaded WITS RCA CSV file.")
        parser.add_argument("--reporter", required=True, help="Reporter country name as stored in DB, e.g. 'KoreaRepublic'.")
        parser.add_argument("--year", required=True, type=int, help="Year to validate, e.g. 2022.")
        parser.add_argument("--wits-reporter", help="Reporter name as it appears in the WITS CSV (if different from --reporter), e.g. 'Korea, Rep.'.")

    def handle(self, *args, **options):
        wits_csv_path = Path(options["wits_csv"])
        reporter = options["reporter"]
        year = options["year"]
        wits_reporter = options.get("wits_reporter") or reporter

        if not wits_csv_path.exists():
            raise CommandError(f"WITS CSV not found: {wits_csv_path}")

        self.stdout.write("Running TCI pipeline to compute RCA scores ...")
        calculator = TCICalculator()
        calculator._load_from_db()
        calculator._filter_by_scope_and_year()
        calculator._calculate_tci_drysdale_garnaut()
        calculator._calculate_rca_and_tci_rca()

        # RCA Reporter Export is identical across partners (depends only on reporter + world exports).
        # Use whichever partner partition is available.
        available_partners = list(calculator.hs6_trade_data_by_partner.keys())
        if not available_partners:
            raise CommandError("No HS6 trade data computed. Check that the DB has data.")
        partner_key = "China" if "China" in available_partners else available_partners[0]

        hs6_data = calculator.hs6_trade_data_by_partner[partner_key]
        our_rca = (
            hs6_data[
                (hs6_data["Country"] == reporter)
                & (hs6_data["Year"] == str(year))
            ]
            [["Product code", "RCA Reporter Export"]]
            .rename(columns={"Product code": "product_code", "RCA Reporter Export": "our_rca"})
            .copy()
        )

        if our_rca.empty:
            raise CommandError(
                f"No computed RCA data for reporter='{reporter}', year={year}. "
                f"Available reporters: {hs6_data['Country'].unique().tolist()}"
            )

        self.stdout.write(f"Loaded {len(our_rca)} HS6 rows from our pipeline (reporter: {reporter}, year: {year}).")

        wits_df = self._load_wits_csv(wits_csv_path, wits_reporter, year)
        self.stdout.write(f"Loaded {len(wits_df)} HS6 rows from WITS CSV.")

        merged = pd.merge(our_rca, wits_df, on="product_code", how="outer", indicator=True)

        only_ours = merged[merged["_merge"] == "left_only"]
        only_wits = merged[merged["_merge"] == "right_only"]
        both = merged[merged["_merge"] == "both"].copy()

        both["abs_diff"] = (both["our_rca"] - both["wits_rca"]).abs()
        both["pct_diff"] = both["abs_diff"] / both["wits_rca"].replace(0, float("nan"))

        correlation = both["our_rca"].corr(both["wits_rca"])
        mean_abs_pct_diff = both["pct_diff"].mean()

        discrepancies = both.sort_values("abs_diff", ascending=False)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"RCA VALIDATION REPORT: {reporter} / {year}")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  HS6 products in both:      {len(both)}")
        self.stdout.write(f"  Pearson correlation:       {correlation:.4f}")
        self.stdout.write(f"  Mean absolute % diff:      {mean_abs_pct_diff*100:.2f}%")
        self.stdout.write(f"  Only in our data:          {len(only_ours)}")
        self.stdout.write(f"  Only in WITS:              {len(only_wits)}")

        self.stdout.write(f"\nTop {TOP_DISCREPANCY_DISPLAY} discrepancies (by absolute diff):")
        self.stdout.write(f"  {'HS6':>8}  {'Our RCA':>10}  {'WITS RCA':>10}  {'Diff%':>8}")
        for _, row in discrepancies.head(TOP_DISCREPANCY_DISPLAY).iterrows():
            pct = f"{row['pct_diff']*100:.1f}%" if pd.notna(row["pct_diff"]) else "N/A"
            self.stdout.write(
                f"  {row['product_code']:>8}  {row['our_rca']:>10.4f}  {row['wits_rca']:>10.4f}  {pct:>8}"
            )

        self.stdout.write("")

    def _load_wits_csv(self, path: Path, reporter: str, year: int) -> pd.DataFrame:
        raw = pd.read_csv(path, dtype=str)
        raw.columns = raw.columns.str.strip().str.lower()

        reporter_col = self._find_column(raw, ["reportername", "reporter name", "reporter", "country"])
        year_col     = self._find_column(raw, ["year", "period"])
        product_col  = self._find_column(raw, ["productcode", "product code", "hs6", "commodity code"])
        # WITS has a known typo: "Reavealed Comparative Advantage" — match on "advantage" to handle both spellings
        rca_col      = self._find_column(raw, ["advantage", "rca", "balassa"])

        partner_col = self._find_column(raw, ["partneriso3", "partneriso", "partner iso", "partner"])
        filtered = raw[
            raw[reporter_col].str.strip().str.lower().str.contains(reporter.lower(), na=False)
            & (raw[year_col].str.strip() == str(year))
            & (raw[partner_col].str.strip().str.upper() == "WLD")
        ].copy()

        if filtered.empty:
            raise CommandError(
                f"No rows found in WITS CSV for reporter containing '{reporter}' and year {year}.\n"
                f"Available reporters: {raw[reporter_col].unique()[:10].tolist()}"
            )

        # Zero-pad to 6 digits to match DB product_code format
        filtered["product_code"] = filtered[product_col].str.strip().str.zfill(6)
        filtered["wits_rca"] = pd.to_numeric(filtered[rca_col], errors="coerce")
        return filtered[["product_code", "wits_rca"]].dropna(subset=["wits_rca"])

    @staticmethod
    def _find_column(df: pd.DataFrame, candidates: list[str]) -> str:
        for candidate in candidates:
            for col in df.columns:
                if candidate in col:
                    return col
        raise CommandError(
            f"Could not find a column matching any of {candidates} in WITS CSV.\n"
            f"Available columns: {df.columns.tolist()}"
        )

import comtradeapicall
import pandas as pd
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from loadFiles.models import CountryExportToWorld, PartnerImportFromWorld
from loadFiles.services.ComtradeDownload import ComtradeReferenceData

MATCH_TOLERANCE = 0.05  # 5%
TOP_MISMATCH_DISPLAY = 20
# previewFinalData is capped at 500 rows (free API). getFinalData requires a paid subscription.
COMTRADE_API_ROW_LIMIT = 500


class Command(BaseCommand):
    help = (
        "Compare DB trade values against Comtrade API data for one country/year. "
        "Use --flow X to validate reporter export data (CountryExportToWorld), "
        "or --flow M to validate partner import data (PartnerImportFromWorld). "
        "Uses the free preview API (capped at 500 rows)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--country", required=True, help="Country ISO alpha-2 code, e.g. VN, CN, US")
        parser.add_argument("--year", required=True, type=int, help="Year to validate, e.g. 2022")
        parser.add_argument(
            "--flow",
            choices=["X", "M"],
            default="X",
            help="X = exports (validates CountryExportToWorld). M = imports (validates PartnerImportFromWorld).",
        )
        parser.add_argument(
            "--db-name",
            help="Country name exactly as stored in DB (e.g. 'Vietnam', 'China'). Defaults to --country value.",
        )
        parser.add_argument(
            "--comtrade-code",
            type=int,
            help="Override Comtrade numeric country code (e.g. 704 for Viet Nam). "
                 "Use when the reference CSV resolves to a historical/dissolved country code.",
        )

    def handle(self, *args, **options):
        country_iso = options["country"]
        year = options["year"]
        flow = options["flow"]
        db_name = options.get("db_name") or country_iso
        comtrade_code_override = options.get("comtrade_code")

        if comtrade_code_override:
            country_code = comtrade_code_override
        else:
            country_code = self._get_comtrade_country_code(country_iso)

        flow_label = "exports to world" if flow == "X" else "imports from world"
        self.stdout.write(f"Fetching Comtrade {flow_label} for {country_iso} ({country_code}), year {year} ...")
        self.stdout.write(f"  Note: free API limited to {COMTRADE_API_ROW_LIMIT} rows per request.")

        comtrade_df = self._fetch_comtrade_data(country_code, year, flow)
        if comtrade_df is None or comtrade_df.empty:
            raise CommandError(
                f"No Comtrade data returned for {country_iso} (code {country_code}), year {year}, flow {flow}.\n"
                f"Tip: verify the correct Comtrade code with:\n"
                f"  python -c \"import comtradeapicall; r=comtradeapicall.getReference('reporter'); "
                f"print(r[r.reporterCodeIsoAlpha2=='{country_iso}'][['reporterCode','text']])\""
            )

        comtrade_df = comtrade_df.rename(columns={"cmdCode": "product_code", "primaryValue": "comtrade_value_usd"})
        comtrade_df["product_code"] = comtrade_df["product_code"].astype(str).str.strip()
        comtrade_df = comtrade_df[["product_code", "comtrade_value_usd"]].dropna(subset=["comtrade_value_usd"])
        self.stdout.write(f"  Received {len(comtrade_df)} rows from Comtrade (cap: {COMTRADE_API_ROW_LIMIT}).")

        db_df = self._load_db_data(db_name, str(year), flow)
        self.stdout.write(f"  Found {len(db_df)} rows in DB.")

        # Comtrade returns USD; DB stores USD thousands
        comtrade_df["comtrade_value_thousands"] = comtrade_df["comtrade_value_usd"] / 1000

        merged = pd.merge(
            comtrade_df[["product_code", "comtrade_value_thousands"]],
            db_df,
            on="product_code",
            how="outer",
            indicator=True,
        )

        only_in_comtrade = merged[merged["_merge"] == "left_only"]["product_code"].tolist()
        only_in_db       = merged[merged["_merge"] == "right_only"]["product_code"].tolist()
        both             = merged[merged["_merge"] == "both"].copy()

        both["abs_diff"] = (both["comtrade_value_thousands"] - both["db_value_usd_thousands"]).abs()
        both["pct_diff"] = both["abs_diff"] / both["comtrade_value_thousands"].replace(0, float("nan"))

        matched   = both[both["pct_diff"] <= MATCH_TOLERANCE]
        mismatched = both[both["pct_diff"] > MATCH_TOLERANCE].sort_values("abs_diff", ascending=False)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"VALIDATION REPORT: {country_iso} / {year} / flow={flow} ({flow_label})")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Products compared (in both):   {len(both)}")
        self.stdout.write(f"  Matched within {MATCH_TOLERANCE*100:.0f}%:            {len(matched)} ({len(matched)/max(len(both),1)*100:.1f}%)")
        self.stdout.write(f"  Mismatched (>{MATCH_TOLERANCE*100:.0f}% diff):         {len(mismatched)}")
        self.stdout.write(f"  Only in Comtrade (not in DB): {len(only_in_comtrade)}")
        self.stdout.write(f"  Only in DB (not in Comtrade): {len(only_in_db)} (expected — DB has full HS6 universe)")

        if not mismatched.empty:
            self.stdout.write(f"\nTop {TOP_MISMATCH_DISPLAY} mismatches (by absolute diff, USD thousands):")
            self.stdout.write(f"  {'Product':>10}  {'Comtrade':>14}  {'DB':>14}  {'Diff%':>8}")
            for _, row in mismatched.head(TOP_MISMATCH_DISPLAY).iterrows():
                pct = f"{row['pct_diff']*100:.1f}%" if pd.notna(row["pct_diff"]) else "N/A"
                self.stdout.write(
                    f"  {row['product_code']:>10}  {row['comtrade_value_thousands']:>14,.1f}"
                    f"  {row['db_value_usd_thousands']:>14,.1f}  {pct:>8}"
                )

        if only_in_comtrade:
            self.stdout.write(f"\nFirst 10 products in Comtrade but missing from DB:")
            self.stdout.write("  " + ", ".join(only_in_comtrade[:10]))

        self.stdout.write("")

    def _load_db_data(self, db_name: str, year: str, flow: str) -> pd.DataFrame:
        if flow == "X":
            records = list(
                CountryExportToWorld.objects
                .filter(reporter=db_name, year=year)
                .values("product_code", "value_usd_thousands")
            )
            if not records:
                raise CommandError(
                    f"No CountryExportToWorld records found for reporter='{db_name}', year={year}. "
                    "Check --db-name matches exactly what is stored in the DB."
                )
        else:
            records = list(
                PartnerImportFromWorld.objects
                .filter(partner=db_name, year=year)
                .values("product_code", "value_usd_thousands")
            )
            if not records:
                raise CommandError(
                    f"No PartnerImportFromWorld records found for partner='{db_name}', year={year}. "
                    "Check --db-name matches exactly what is stored in the DB."
                )

        df = pd.DataFrame(records)
        df["product_code"] = df["product_code"].astype(str).str.strip()
        return df.rename(columns={"value_usd_thousands": "db_value_usd_thousands"})

    def _get_comtrade_country_code(self, country_iso: str) -> int:
        ref = ComtradeReferenceData()
        ref_dir = Path(ref.export_location)
        csv_files = sorted(ref_dir.glob("country_code_reference_data*.csv"), reverse=True)
        if not csv_files:
            raise CommandError(
                "No country code reference CSV found. Run update_reference_for_country_id first."
            )
        df = pd.read_csv(csv_files[0])
        matches = df[df["IsoAlpha2"].str.upper() == country_iso.upper()]
        if matches.empty:
            raise CommandError(f"Country ISO '{country_iso}' not found in country code reference.")

        # Prefer current country: filter out historical entries (marked with year range in name)
        current = matches[~matches["text"].str.contains(r"\(.*\d{4}", regex=True, na=False)]
        best = current if not current.empty else matches
        return int(best.iloc[0]["Code"])

    def _fetch_comtrade_data(self, country_code: int, year: int, flow: str):
        return comtradeapicall.previewFinalData(
            typeCode="C",
            freqCode="A",
            clCode="HS",
            period=str(year),
            reporterCode=country_code,
            cmdCode="AG6",
            flowCode=flow,
            partnerCode="0",
            partner2Code=None,
            customsCode=None,
            motCode=None,
            format_output="JSON",
            aggregateBy=None,
            breakdownMode="classic",
            includeDesc=False,
        )

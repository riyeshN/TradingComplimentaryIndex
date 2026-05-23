"""
Load a single HS-revision's HS6 → SITC Rev.4 correspondence into the
HSSITCConcordance table, tagged by HS revision (vintage-aware).

The trade panel spans multiple HS revisions (HS2007/2012/2017/2022). The same
HS6 code can map to different SITC codes across revisions, so each row is keyed
by (product_code, hs_revision). A year's HS6 row is later assigned the SITC
section from the revision active that year (see
`trade_data_loader.hs_revision_for_year`). Run this command once per revision.

The UN correspondence files are heterogeneous (.xls / .xlsx, different sheet
names, title-block junk rows, dotted or plain codes), so columns are located by
**pattern**: read the conversion sheet header-less, score every column by how
many cells look like an HS6 code, and take the SITC column as the best
SITC-code-matching column. This works uniformly across all four UN vintages.

Source: UN Statistics Division correspondence tables,
https://unstats.un.org/unsd/trade/classifications/correspondence-tables.asp

Idempotent per revision — replaces only the given revision's rows.

Usage (run once per revision):
    python manage.py load_hs_sitc_concordance --csv "data/reference_data/UN Comtrade Conversion table HS2007 to SITCRev4.xls" --revision 2007
    python manage.py load_hs_sitc_concordance --csv "data/reference_data/HS 2012 to SITC Rev.4 Correlation and conversion tables.xls" --revision 2012
    python manage.py load_hs_sitc_concordance --csv data/reference_data/HS2017toSITC4ConversionAndCorrelationTables.xlsx --revision 2017
    python manage.py load_hs_sitc_concordance --csv data/reference_data/HS2022toSITC4ConversionAndCorrelationTables.xlsx --revision 2022
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from loadFiles.models import HSSITCConcordance

# HS6 subheading: 4-digit heading + 2-digit subheading, optional separating dot
# (UN files use "0101.21"; TradeMap uses "010121").
HS6_PATTERN = re.compile(r"^\d{4}\.?\d{2}$")
# SITC Rev.4 code: 3+ digits, optional dot ("001.5", "0015", "8966").
SITC_PATTERN = re.compile(r"^\d{3}\.?\d{0,2}$")


def _pick_conversion_sheet(excel_file: pd.ExcelFile) -> str:
    """Prefer the sheet whose name contains 'conversion'; else the first sheet."""
    conversion = [s for s in excel_file.sheet_names if "conversion" in s.lower()]
    return conversion[0] if conversion else excel_file.sheet_names[0]


def _strip(value) -> str:
    return str(value).replace(" ", "")


def _locate_columns(frame: pd.DataFrame) -> tuple[int, int]:
    """Return (hs_column_index, sitc_column_index) by pattern-scoring columns.

    HS column = the column with the most HS6-shaped cells. SITC column = the
    column (other than HS) with the most SITC-shaped cells."""
    stripped = frame.apply(lambda col: col.astype(str).map(_strip))
    hs_scores = [stripped[col].str.match(HS6_PATTERN).sum() for col in stripped.columns]
    hs_index = int(pd.Series(hs_scores).idxmax())
    if hs_scores[hs_index] == 0:
        raise CommandError("No column looks like HS6 codes — check the file/sheet.")
    sitc_scores = [
        (stripped[col].str.match(SITC_PATTERN).sum() if col != hs_index else -1)
        for col in stripped.columns
    ]
    sitc_index = int(pd.Series(sitc_scores).idxmax())
    if sitc_scores[sitc_index] <= 0:
        raise CommandError("No column looks like SITC codes — check the file/sheet.")
    return hs_index, sitc_index


class Command(BaseCommand):
    help = "Load one HS-revision's HS6 → SITC Rev.4 concordance into HSSITCConcordance."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv", required=True,
            help="Path to the UN HS→SITC Rev.4 correspondence CSV or XLS/XLSX.",
        )
        parser.add_argument(
            "--revision", required=True,
            choices=["2002", "2007", "2012", "2017", "2022"],
            help="HS revision this file represents (tags every row).",
        )
        parser.add_argument(
            "--sheet", default=None,
            help="Worksheet name (XLS/XLSX). Default: auto-pick the 'Conversion' sheet.",
        )

    def handle(self, *args, **options):
        source_path = Path(options["csv"])
        revision = options["revision"]
        if not source_path.exists():
            raise CommandError(f"File not found: {source_path}")

        if source_path.suffix.lower() in (".xlsx", ".xls"):
            excel_file = pd.ExcelFile(source_path)
            sheet = options["sheet"] or _pick_conversion_sheet(excel_file)
            raw = pd.read_excel(excel_file, sheet_name=sheet, dtype=str, header=None)
            self.stdout.write(f"Sheet: '{sheet}'")
        else:
            raw = pd.read_csv(source_path, dtype=str, header=None)

        hs_index, sitc_index = _locate_columns(raw)
        self.stdout.write(f"HS column: {hs_index}  |  SITC column: {sitc_index}")

        records: dict[str, tuple[str, str]] = {}
        skipped = 0
        for hs_raw, sitc_raw in zip(raw.iloc[:, hs_index], raw.iloc[:, sitc_index]):
            hs_value = _strip(hs_raw)
            sitc_value = _strip(sitc_raw)
            if not HS6_PATTERN.match(hs_value) or not SITC_PATTERN.match(sitc_value):
                skipped += 1
                continue
            hs6 = hs_value.replace(".", "").zfill(6)[:6]
            sitc = sitc_value.replace(".", "")
            records[hs6] = (sitc, sitc[0])

        if not records:
            raise CommandError("No valid HS→SITC rows parsed; check the file/sheet.")

        objects = [
            HSSITCConcordance(
                product_code=hs6, hs_revision=revision,
                sitc_code=sitc, sitc_section=section,
            )
            for hs6, (sitc, section) in records.items()
        ]
        HSSITCConcordance.objects.filter(hs_revision=revision).delete()
        HSSITCConcordance.objects.bulk_create(objects, batch_size=1000)

        sections = sorted({section for _, section in records.values()})
        self.stdout.write(
            f"Loaded {len(objects)} HS{revision}→SITC rows "
            f"({skipped} non-data rows skipped). SITC sections present: {sections}"
        )

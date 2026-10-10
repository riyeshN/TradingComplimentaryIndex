"""
Export the Cij weighting-comparison deliverable (Excel + Word).

Per (reporter, partner, year, HS2 chapter), three Cij forms side by side:
  - Cij_Drysdale              = Σ HS6 Drysdale–Garnaut Cij (= pipeline TCI_DG_2digit)
  - Cij_WorldShareWeighted    = product of world-share-weighted (canonical) HS2 RCAs
                                (= pipeline TCI_RCA_Product_2digit)
  - Cij_ImporterShareWeighted = product of own-trade-share-weighted HS2 RCAs

Shows what changes when the per-HS6 detail is weighted by world-export shares
vs by the reporter's/partner's own trade shares. See
`loadFiles/services/exporters/cij_comparison.py` for the formulas.

Standalone — reads straight from the DB, no full TCI pipeline re-run. If any
group's own-share weights do not sum to 1.0, the command prints a WARNING and
records the affected groups in both deliverables, but still writes the files.

Output folder: `data/TradeMapData/export/cij_comparison/`.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from loadFiles.services.exporters.cij_comparison import (
    DEFAULT_CHAPTERS,
    export_cij_comparison,
)


class Command(BaseCommand):
    help = "Export the Cij weighting-comparison (world vs own share) Excel + Word."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir", default="data/TradeMapData/export/cij_comparison",
            help="Output folder (default data/TradeMapData/export/cij_comparison).",
        )
        parser.add_argument(
            "--chapters", nargs="+", default=list(DEFAULT_CHAPTERS),
            help="HS2 chapters to report (default: the 10 strategic chapters).",
        )
        parser.add_argument(
            "--countries", nargs="+", default=None,
            help="Restrict reporters (default: all reporters in the DB).",
        )
        parser.add_argument("--year-min", type=int, default=2001)
        parser.add_argument("--year-max", type=int, default=2024)

    def handle(self, *args, **options):
        excel_path, word_path, anomalies = export_cij_comparison(
            export_dir=Path(options["output_dir"]),
            chapters=tuple(options["chapters"]),
            year_min=options["year_min"],
            year_max=options["year_max"],
            countries=options["countries"],
        )

        self.stdout.write(self.style.SUCCESS(f"Wrote {excel_path}"))
        self.stdout.write(self.style.SUCCESS(f"Wrote {word_path}"))

        if anomalies.empty:
            self.stdout.write(self.style.SUCCESS(
                "Data quality OK — all own-share weights sum to 1.0."
            ))
        else:
            self.stderr.write(self.style.WARNING(
                f"DATA QUALITY WARNING: {len(anomalies)} group(s) have own-share "
                "weights that do not sum to 1.0 (HS6 lines dropped by the "
                "world-export join). Files were still written — see the 'Data "
                "Quality' sheet and the Word 'Data notes' section."
            ))

"""
Generate the RCA-only deliverable (strategic / HS2 scope).

  - `RCA_only.docx` — import RCA tables for the US and China by HS2 sector,
    plus an HS 8541 / 8542 semiconductor table
  - `RCA_import_evolution_US.png` and `RCA_import_evolution_China.png` —
    one line per strategic HS2 chapter, 2001-2024

Output folder: `data/TradeMapData/export/strategic/rca_tables/`. Standalone —
no full pipeline re-run needed; loads via `TCICalculator.run_indicators()`.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from loadFiles.services.TCICalculator import TCICalculator
from loadFiles.services.scope import SCOPE_STRATEGIC
from loadFiles.services.exporters.rca_only import export_rca_only


class Command(BaseCommand):
    help = "Export the RCA-only Word doc + US/China import-RCA evolution charts (strategic HS2)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir", default="data/TradeMapData/export/strategic/rca_tables",
            help="Output folder (default data/TradeMapData/export/strategic/rca_tables).",
        )

    def handle(self, *args, **options):
        calc = TCICalculator(scope=SCOPE_STRATEGIC)
        calc.run_indicators()
        out_path = export_rca_only(
            calc.hs2_index_by_partner,
            calc.hs4_index_by_partner,
            calc.hs6_with_indicators_by_partner,
            Path(options["output_dir"]),
        )
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path} and accompanying PNGs."))

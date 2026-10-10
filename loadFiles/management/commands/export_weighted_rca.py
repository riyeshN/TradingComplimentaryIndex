"""
Export the importer-weighted RCA deliverable (Excel + Word) at an HS tier.

  - `Weighted_RCA_{tier}.xlsx` — long sheet + one pivot per partner + a Data
    Quality sheet
  - `Weighted_RCA_{tier}.docx` — report-ready table per partner + method/data note
  where {tier} is HS2 (default) or HS4.

RCA(tier) = Σ_k w_k · RCA_import_k, with the importer's within-tier trade share
w_k = M_jk / Σ_k M_jk as the weight (weights sum to 1). See
`loadFiles/services/exporters/weighted_rca.py` for the full method note.

Examples:
  # default: 10 strategic HS2 chapters
  python manage.py export_weighted_rca
  # HS4 headings 8541 & 8542 (semiconductors), weighted average of HS6
  python manage.py export_weighted_rca --digits 4 --chapters 8541 8542

Standalone — reads straight from the DB, no full TCI pipeline re-run. If any
(year, partner, tier) group's weights do not sum to 1.0, the command prints a
WARNING and records the affected groups in both deliverables, but still writes
the files (warn, don't fail).

Output folder: `data/TradeMapData/export/weighted_rca/`.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from loadFiles.services.exporters.weighted_rca import (
    DEFAULT_CHAPTERS,
    export_weighted_rca,
)
from loadFiles.services.exporters.rca_only import CHAPTER_LABELS
from loadFiles.services.scope import SCOPE_ICT


class Command(BaseCommand):
    help = "Export the importer-weighted RCA Excel + Word deliverables (HS2 or HS4)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir", default="data/TradeMapData/export/weighted_rca",
            help="Output folder (default data/TradeMapData/export/weighted_rca).",
        )
        parser.add_argument(
            "--digits", type=int, choices=(2, 4), default=2,
            help="HS tier to aggregate to: 2 = HS2 chapters (default), 4 = HS4 headings.",
        )
        parser.add_argument(
            "--chapters", nargs="+", default=None,
            help="Tier codes to report (must match --digits length). "
                 "Default: the 10 strategic HS2 chapters when --digits 2.",
        )
        parser.add_argument("--year-min", type=int, default=2001)
        parser.add_argument("--year-max", type=int, default=2024)

    def handle(self, *args, **options):
        digits = options["digits"]
        codes = options["chapters"]
        if codes is None:
            if digits != 2:
                raise SystemExit("--chapters is required when --digits is not 2.")
            codes = list(DEFAULT_CHAPTERS)

        # Labels: HS2 strategic-chapter labels, or HS4 ICT-heading labels.
        if digits == 2:
            labels, tier_name = CHAPTER_LABELS, 'HS2'
        else:
            labels, tier_name = SCOPE_ICT.primary_labels, 'HS4'

        excel_path, word_path, chart_paths, anomalies = export_weighted_rca(
            export_dir=Path(options["output_dir"]),
            codes=tuple(codes),
            year_min=options["year_min"],
            year_max=options["year_max"],
            digits=digits,
            labels=labels,
            tier_name=tier_name,
        )

        self.stdout.write(self.style.SUCCESS(f"Wrote {excel_path}"))
        self.stdout.write(self.style.SUCCESS(f"Wrote {word_path}"))
        for p in chart_paths:
            self.stdout.write(self.style.SUCCESS(f"Wrote {p}"))

        if anomalies.empty:
            self.stdout.write(self.style.SUCCESS(
                f"Data quality OK — all within-{tier_name} weights sum to 1.0."
            ))
        else:
            self.stderr.write(self.style.WARNING(
                f"DATA QUALITY WARNING: {len(anomalies)} group(s) have weights "
                "that do not sum to 1.0 (HS6 lines dropped by the world-export "
                "join). Files were still written — see the 'Data Quality' sheet "
                "and the Word 'Data notes' section:"
            ))
            for _, r in anomalies.iterrows():
                self.stderr.write(self.style.WARNING(
                    f"  {int(r['Year'])} · {r['Partner']} · HS {r['Tier']}: "
                    f"Σw = {r['weight_check']:.4f} "
                    f"(shortfall {r['weight_shortfall']:.4f}, "
                    f"n={int(r['n_hs6_lines'])})"
                ))

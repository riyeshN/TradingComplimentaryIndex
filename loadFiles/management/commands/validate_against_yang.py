"""
Validate against Lingling Yang (2023), Table 3.

Yang reports Cij for China (exporter) vs the CEE country group (importer,
aggregated), by SITC Rev.4 section (SITC0–SITC9), 2010–2021.

This command runs the **exact same pipeline** as the ICT/strategic analyses:
`TCICalculator(scope=SCOPE_YANG, partner_names=('CCE',)).run_indicators()`.
The china→CCE Cij/RCA values come from the pipeline's `_calculate_*` and
`_aggregate_to_sitc` methods — there is NO formula re-implementation here. The
command only reads `calc.sitc_index_by_partner['CCE']` and lines it up against
Yang's published table.

Two pipeline forms are reported per SITC section:
  - `TCI_DG_sitc`          — Drysdale-Garnaut weighted (Σ HS6 DG).
  - `TCI_RCA_Product_sitc` — unweighted RCA product (Yang Table 3 form).

Writes docs/yang_validation.csv. No pass/fail assertion.
Prerequisites: `china_CCE.txt` loaded; `HSSITCConcordance` populated
(`load_hs_sitc_concordance`).
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand, CommandError

from loadFiles.models import HSSITCConcordance
from loadFiles.services.TCICalculator import TCICalculator
from loadFiles.services.scope import SCOPE_YANG


CCE_PARTNER = 'CCE'
OUTPUT_PATH = Path('docs/yang_validation.csv')

# Yang (2023) Table 3, page 144. Rows = SITC section, columns = years 2010..2021.
YANG_YEARS = list(range(2010, 2022))
YANG_TABLE = {
    '0': [0.47, 0.49, 0.51, 0.52, 0.54, 0.55, 0.57, 0.58, 0.59, 0.63, 0.65, 0.66],
    '1': [0.15, 0.17, 0.16, 0.18, 0.20, 0.19, 0.23, 0.25, 0.28, 0.27, 0.29, 0.31],
    '2': [0.13, 0.13, 0.11, 0.14, 0.12, 0.15, 0.17, 0.19, 0.21, 0.23, 0.28, 0.30],
    '3': [0.12, 0.17, 0.14, 0.16, 0.15, 0.17, 0.19, 0.18, 0.23, 0.26, 0.29, 0.33],
    '4': [0.03, 0.03, 0.02, 0.04, 0.03, 0.05, 0.07, 0.09, 0.12, 0.16, 0.18, 0.19],
    '5': [0.52, 0.57, 0.56, 0.50, 0.55, 0.56, 0.59, 0.62, 0.65, 0.68, 0.73, 0.75],
    '6': [1.53, 1.52, 1.53, 1.52, 1.54, 1.56, 1.59, 1.62, 1.65, 1.67, 1.69, 1.72],
    '7': [1.49, 1.32, 1.45, 1.61, 1.65, 1.67, 1.69, 1.71, 1.76, 1.79, 1.82, 1.84],
    '8': [1.79, 1.67, 1.89, 1.71, 1.83, 1.90, 1.92, 1.93, 1.96, 1.97, 2.01, 2.05],
    '9': [0.03, 0.01, 0.03, 0.03, 0.04, 0.03, 0.05, 0.07, 0.08, 0.08, 0.09, 0.12],
}


def _rel_pct(pipeline_value, published):
    if published == 0 or pipeline_value is None or np.isnan(pipeline_value):
        return ''
    return round(100.0 * (pipeline_value - published) / published, 1)


class Command(BaseCommand):
    help = "Compare pipeline Cij (China→CEE, by SITC) vs Yang (2023) Table 3."

    def handle(self, *args, **options):
        if not HSSITCConcordance.objects.exists():
            raise CommandError(
                "HSSITCConcordance table is empty. Load it first:\n"
                "  python manage.py load_hs_sitc_concordance --csv <HS-SITC file>"
            )

        # Same pipeline as the main analyses — china reporter, CCE partner.
        calc = TCICalculator(scope=SCOPE_YANG, partner_names=(CCE_PARTNER,))
        calc.run_indicators()

        sitc = calc.sitc_index_by_partner.get(CCE_PARTNER)
        if sitc is None or sitc.empty:
            raise CommandError(
                f"No SITC output for '{CCE_PARTNER}'. Is china_CCE.txt loaded?"
            )
        sitc = sitc.copy()
        sitc['Year'] = sitc['Year'].astype(int)

        rows = []
        for section, published_series in YANG_TABLE.items():
            for year, published in zip(YANG_YEARS, published_series):
                match = sitc[(sitc['SITC'] == section) & (sitc['Year'] == year)]
                if match.empty:
                    rows.append({
                        'Year': year, 'SITC': section,
                        'Pipeline_DG_weighted': '', 'Pipeline_RCA_Product_unweighted': '',
                        'Yang_Published': published,
                        'Diff_vs_DG_Pct': '', 'Diff_vs_RCAproduct_Pct': '',
                    })
                    continue
                dg = float(match['TCI_DG_sitc'].iloc[0])
                rca_product = float(match['TCI_RCA_Product_sitc'].iloc[0])
                rows.append({
                    'Year': year, 'SITC': section,
                    'Pipeline_DG_weighted': round(dg, 4),
                    'Pipeline_RCA_Product_unweighted': round(rca_product, 4),
                    'Yang_Published': published,
                    'Diff_vs_DG_Pct': _rel_pct(dg, published),
                    'Diff_vs_RCAproduct_Pct': _rel_pct(rca_product, published),
                })

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT_PATH.open('w', newline='') as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=['Year', 'SITC', 'Pipeline_DG_weighted',
                            'Pipeline_RCA_Product_unweighted', 'Yang_Published',
                            'Diff_vs_DG_Pct', 'Diff_vs_RCAproduct_Pct'],
            )
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(f"Wrote {OUTPUT_PATH} with {len(rows)} cells.")

        # Band breakdown for the RCA-product form (the one comparable to Yang).
        diffs = [r['Diff_vs_RCAproduct_Pct'] for r in rows
                 if isinstance(r['Diff_vs_RCAproduct_Pct'], (int, float))]
        bands = {'≤10%': 0, '10–25%': 0, '25–50%': 0, '>50%': 0}
        for d in diffs:
            mag = abs(d)
            if mag <= 10:
                bands['≤10%'] += 1
            elif mag <= 25:
                bands['10–25%'] += 1
            elif mag <= 50:
                bands['25–50%'] += 1
            else:
                bands['>50%'] += 1
        self.stdout.write("RCA-product vs Yang — relative-difference bands:")
        for band, count in bands.items():
            pct = 100.0 * count / len(diffs) if diffs else 0
            self.stdout.write(f"  {band:>8s}: {count:3d} / {len(diffs)} ({pct:.1f}%)")

        self.stdout.write("\nPer-SITC (2021): DG_weighted | RCA_product | Yang")
        for section in YANG_TABLE:
            m = sitc[(sitc['SITC'] == section) & (sitc['Year'] == 2021)]
            dg = float(m['TCI_DG_sitc'].iloc[0]) if not m.empty else float('nan')
            rp = float(m['TCI_RCA_Product_sitc'].iloc[0]) if not m.empty else float('nan')
            self.stdout.write(
                f"  SITC{section}: {dg:7.3f} | {rp:7.3f} | {YANG_TABLE[section][-1]:.2f}"
            )

"""
Cij weighting-comparison deliverable (strategic HS2 scope).

Shows, per (reporter, partner, year, HS2 chapter), three forms of the trade
complementarity index Cij — identical except for how the per-HS6 detail is
weighted when it is aggregated to the chapter:

    Cij_Drysdale              = Σ_k  RCA_x_k · RCA_m_k · (W_k / W)
    Cij_WorldShareWeighted    = RCA_x_HS2(world)  × RCA_m_HS2(world)
    Cij_ImporterShareWeighted = RCA_x_HS2(own)    × RCA_m_HS2(own)

where for HS6 product k inside the chapter:
    RCA_x_k = (X_ik / X_i) ÷ (W_k / W)      reporter i export RCA
    RCA_m_k = (M_jk / M_j) ÷ (W_k / W)      partner  j import RCA

and the two product forms are products of *separately aggregated* tier RCAs:
    world weighting:  weight ∝ W_k  (world-export share)  → reproduces the
                      orthodox Balassa ratio-of-sums HS2 RCA, so this column is
                      the standard one. Verified equal to the pipeline's
                      TCI_RCA_Product_2digit.
    own weighting:    export side weight ∝ X_ik (reporter's own export share),
                      import side weight ∝ M_jk (partner's own import share).
                      Weights sum to 1 within the chapter (weight_check).

Cij_Drysdale is the sum of the HS6 Drysdale–Garnaut Cij and equals the
pipeline's TCI_DG_2digit. The two products do NOT equal the Drysdale sum in
general (product-of-averages ≠ sum-of-products) — that divergence, and the
world-vs-own contrast, is the point of the document.

The computation is plain SQL run through the Django DB connection — same
pattern as `weighted_rca.py`. Output folder:
`data/TradeMapData/export/cij_comparison/`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .rca_only import CHAPTER_LABELS, STRATEGIC_CHAPTERS
from .word_summary import _apply_page_layout, _format_number, _style_table

DATA_SOURCE_TEXT = 'Data source: Calculated from the World Trade Map.'
WEIGHT_TOLERANCE = 1e-6
DEFAULT_CHAPTERS = STRATEGIC_CHAPTERS
PARTNERS = ('US', 'China')

# Cij forms, in display order: (output column, short label for headers).
CIJ_FORMS = (
    ('Cij_Drysdale', 'Drysdale (Σ HS6)'),
    ('Cij_WorldShareWeighted', 'World-wt'),
    ('Cij_ImporterShareWeighted', 'Own-wt'),
)

# Raw SQL. Chapter IN-list bound via %(chapters)s substitution; year bounds via
# %%s -> %s parameters. 8524 (chapter 85) is dropped before 2022 to match the
# pipeline's RESTRICTED_CODE_FIRST_VALID_YEAR.
_SQL_TEMPLATE = """
WITH
world_hs6 AS (
    SELECT year, product_code, SUBSTR(product_code,1,2) hs2, value_usd_thousands wk
    FROM loadFiles_worldexport
    WHERE product_code <> 'TOTAL'
      AND NOT (SUBSTR(product_code,1,4)='8524' AND year < 2022)
),
world_total AS (
    SELECT year, value_usd_thousands w FROM loadFiles_worldexport WHERE product_code='TOTAL'
),
world_hs2 AS (
    SELECT year, hs2, SUM(wk) w_hs2 FROM world_hs6 GROUP BY year, hs2
),
rep_hs6 AS (
    SELECT reporter, year, product_code, SUBSTR(product_code,1,2) hs2, value_usd_thousands xik
    FROM loadFiles_countryexporttoworld
    WHERE product_code <> 'TOTAL'
      AND NOT (SUBSTR(product_code,1,4)='8524' AND year < 2022)
),
rep_total AS (
    SELECT reporter, year, value_usd_thousands xi FROM loadFiles_countryexporttoworld WHERE product_code='TOTAL'
),
par_hs6 AS (
    SELECT partner, year, product_code, SUBSTR(product_code,1,2) hs2, value_usd_thousands mjk
    FROM loadFiles_partnerimportfromworld
    WHERE product_code <> 'TOTAL'
      AND NOT (SUBSTR(product_code,1,4)='8524' AND year < 2022)
),
par_total AS (
    SELECT partner, year, value_usd_thousands mj FROM loadFiles_partnerimportfromworld WHERE product_code='TOTAL'
),
-- HS6 reporter-export RCA
exp_rca AS (
    SELECT r.reporter, r.year, r.hs2, r.product_code, r.xik,
           COALESCE( (r.xik / NULLIF(rt.xi,0)) / NULLIF(w.wk / NULLIF(wt.w,0), 0), 0) rca_x_k
    FROM rep_hs6 r
    JOIN rep_total rt ON rt.reporter=r.reporter AND rt.year=r.year
    JOIN world_hs6 w  ON w.product_code=r.product_code AND w.year=r.year
    JOIN world_total wt ON wt.year=r.year
),
-- own-share-weighted export RCA + weight_check, per (reporter, year, hs2)
exp_agg AS (
    SELECT e.reporter, e.year, e.hs2,
           SUM( (e.xik / NULLIF(sx.sx,0)) * e.rca_x_k ) rca_x_own,
           SUM(  e.xik / NULLIF(sx.sx,0) )              wcheck_x,
           COUNT(*) n_x
    FROM exp_rca e
    JOIN (SELECT reporter, year, hs2, SUM(xik) sx FROM exp_rca GROUP BY reporter,year,hs2) sx
      ON sx.reporter=e.reporter AND sx.year=e.year AND sx.hs2=e.hs2
    GROUP BY e.reporter, e.year, e.hs2
),
-- world-share (canonical ratio-of-sums) export RCA, per (reporter, year, hs2)
exp_world AS (
    SELECT r.reporter, r.year, r.hs2,
           COALESCE( (SUM(r.xik)/NULLIF(MAX(rt.xi),0))
                     / NULLIF(MAX(wh.w_hs2)/NULLIF(MAX(wt.w),0),0), 0) rca_x_world
    FROM rep_hs6 r
    JOIN rep_total rt ON rt.reporter=r.reporter AND rt.year=r.year
    JOIN world_hs2 wh ON wh.year=r.year AND wh.hs2=r.hs2
    JOIN world_total wt ON wt.year=r.year
    GROUP BY r.reporter, r.year, r.hs2
),
imp_rca AS (
    SELECT p.partner, p.year, p.hs2, p.product_code, p.mjk,
           COALESCE( (p.mjk / NULLIF(pt.mj,0)) / NULLIF(w.wk / NULLIF(wt.w,0),0), 0) rca_m_k
    FROM par_hs6 p
    JOIN par_total pt ON pt.partner=p.partner AND pt.year=p.year
    JOIN world_hs6 w  ON w.product_code=p.product_code AND w.year=p.year
    JOIN world_total wt ON wt.year=p.year
),
imp_agg AS (
    SELECT i.partner, i.year, i.hs2,
           SUM( (i.mjk / NULLIF(sm.sm,0)) * i.rca_m_k ) rca_m_own,
           SUM(  i.mjk / NULLIF(sm.sm,0) )              wcheck_m,
           COUNT(*) n_m
    FROM imp_rca i
    JOIN (SELECT partner, year, hs2, SUM(mjk) sm FROM imp_rca GROUP BY partner,year,hs2) sm
      ON sm.partner=i.partner AND sm.year=i.year AND sm.hs2=i.hs2
    GROUP BY i.partner, i.year, i.hs2
),
imp_world AS (
    SELECT p.partner, p.year, p.hs2,
           COALESCE( (SUM(p.mjk)/NULLIF(MAX(pt.mj),0))
                     / NULLIF(MAX(wh.w_hs2)/NULLIF(MAX(wt.w),0),0), 0) rca_m_world
    FROM par_hs6 p
    JOIN par_total pt ON pt.partner=p.partner AND pt.year=p.year
    JOIN world_hs2 wh ON wh.year=p.year AND wh.hs2=p.hs2
    JOIN world_total wt ON wt.year=p.year
    GROUP BY p.partner, p.year, p.hs2
),
-- bilateral Drysdale–Garnaut: HS6 Cij summed to the chapter
dg AS (
    SELECT er.reporter, ir.partner, er.year, er.hs2,
           SUM( er.rca_x_k * ir.rca_m_k * (w.wk / NULLIF(wt.w,0)) ) cij_drysdale
    FROM exp_rca er
    JOIN imp_rca ir   ON ir.product_code=er.product_code AND ir.year=er.year
    JOIN world_hs6 w  ON w.product_code=er.product_code AND w.year=er.year
    JOIN world_total wt ON wt.year=er.year
    GROUP BY er.reporter, ir.partner, er.year, er.hs2
)
SELECT d.reporter Country, d.partner Partner, d.year Year, d.hs2 HS2,
       d.cij_drysdale                  Cij_Drysdale,
       ew.rca_x_world * iw.rca_m_world Cij_WorldShareWeighted,
       ea.rca_x_own  * ia.rca_m_own    Cij_ImporterShareWeighted,
       ew.rca_x_world RCA_x_world, iw.rca_m_world RCA_m_world,
       ea.rca_x_own   RCA_x_own,   ia.rca_m_own   RCA_m_own,
       ea.wcheck_x, ia.wcheck_m, ea.n_x, ia.n_m
FROM dg d
JOIN exp_agg   ea ON ea.reporter=d.reporter AND ea.year=d.year AND ea.hs2=d.hs2
JOIN imp_agg   ia ON ia.partner =d.partner  AND ia.year=d.year AND ia.hs2=d.hs2
JOIN exp_world ew ON ew.reporter=d.reporter AND ew.year=d.year AND ew.hs2=d.hs2
JOIN imp_world iw ON iw.partner =d.partner  AND iw.year=d.year AND iw.hs2=d.hs2
WHERE d.hs2 IN (%(chapters)s)
  AND d.year BETWEEN %%s AND %%s
ORDER BY d.partner, d.reporter, d.hs2, d.year
"""


def compute_cij_comparison(
    chapters: tuple[str, ...] = DEFAULT_CHAPTERS,
    year_min: int = 2001,
    year_max: int = 2024,
) -> pd.DataFrame:
    """Run the comparison query and return a long DataFrame, one row per
    (Country, Partner, Year, HS2)."""
    from django.db import connection

    chapters = tuple(str(c).zfill(2) for c in chapters)
    if not all(c.isdigit() and len(c) == 2 for c in chapters):
        raise ValueError(f"chapters must be 2-digit strings, got {chapters!r}")

    placeholders = ', '.join(['%s'] * len(chapters))
    sql = _SQL_TEMPLATE % {'chapters': placeholders}
    params = [*chapters, year_min, year_max]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    df = pd.DataFrame(rows, columns=columns)
    df['Year'] = df['Year'].astype(int)
    return df


def detect_weight_anomalies(df: pd.DataFrame,
                            tolerance: float = WEIGHT_TOLERANCE) -> pd.DataFrame:
    """Rows whose own-share weights (export or import side) do not sum to 1.0 —
    an HS6 line was dropped by the world-export join, so the weighted average
    does not span the chapter. Empty frame means every group is clean."""
    bad = ((df['wcheck_x'] - 1.0).abs() > tolerance) | \
          ((df['wcheck_m'] - 1.0).abs() > tolerance)
    flagged = df[bad].copy()
    flagged['wx_shortfall'] = 1.0 - flagged['wcheck_x']
    flagged['wm_shortfall'] = 1.0 - flagged['wcheck_m']
    return flagged.sort_values(['Partner', 'Country', 'HS2', 'Year'])


# ── Excel ─────────────────────────────────────────────────────────────────

def _write_excel(df: pd.DataFrame, anomalies: pd.DataFrame,
                 chapters: tuple[str, ...], export_dir: Path,
                 log: logging.Logger) -> Path:
    output_path = export_dir / 'Cij_Weighting_Comparison.xlsx'

    long_sheet = df.copy()
    long_sheet['Chapter'] = long_sheet['HS2'].map(CHAPTER_LABELS).fillna('')
    ordered = ['Country', 'Partner', 'Year', 'HS2', 'Chapter',
               'Cij_Drysdale', 'Cij_WorldShareWeighted', 'Cij_ImporterShareWeighted',
               'RCA_x_world', 'RCA_m_world', 'RCA_x_own', 'RCA_m_own',
               'wcheck_x', 'wcheck_m', 'n_x', 'n_m']
    long_sheet = long_sheet[ordered]

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        long_sheet.to_excel(writer, sheet_name='Comparison', index=False)

        # one pivot per partner: index=(Country, Year), columns=HS2 × the 3 forms
        for partner in sorted(df['Partner'].unique()):
            part = df[df['Partner'] == partner]
            value_cols = [c for c, _ in CIJ_FORMS]
            pivot = part.pivot_table(
                index=['Country', 'Year'], columns='HS2',
                values=value_cols, sort=True,
            )
            # flatten MultiIndex columns to "HS2 · form"
            pivot.columns = [f"{hs2} {form.split('_',1)[1] if '_' in form else form}"
                             for form, hs2 in pivot.columns]
            pivot = pivot.sort_index(axis=1)
            sheet = f"Cij - {partner}"[:31]
            pivot.to_excel(writer, sheet_name=sheet)

        if anomalies.empty:
            dq = pd.DataFrame([{
                'Status': 'OK',
                'Note': 'All own-share weights (export and import side) sum to 1.0 '
                        '— no HS6 lines dropped by the world-export join.'}])
        else:
            dq = anomalies[['Country', 'Partner', 'Year', 'HS2',
                            'wcheck_x', 'wx_shortfall', 'wcheck_m', 'wm_shortfall',
                            'n_x', 'n_m']].copy()
            dq.insert(0, 'Status', 'CHECK')
        dq.to_excel(writer, sheet_name='Data Quality', index=False)

    log.info("Wrote %s (%d rows, %d flagged).",
             output_path, len(df), len(anomalies))
    return output_path


# ── Word ──────────────────────────────────────────────────────────────────

def _add_reporter_chapter_table(document, country: str, chapter: str,
                                frame: pd.DataFrame) -> None:
    """One table: rows=year, columns = the three Cij forms for US then China."""
    label = CHAPTER_LABELS.get(chapter, '')
    document.add_heading(f"{country} — HS {chapter} {label}", level=2)

    col_specs = [(p, col, short) for p in PARTNERS for col, short in CIJ_FORMS]
    table = document.add_table(rows=2, cols=1 + len(col_specs))
    table.style = 'Light Grid Accent 1'

    top = table.rows[0].cells
    sub = table.rows[1].cells
    top[0].text = 'Year'
    sub[0].text = ''
    for idx, (partner, _, short) in enumerate(col_specs, start=1):
        top[idx].text = partner
        sub[idx].text = short

    by_year = {int(y): g for y, g in frame.groupby('Year')}
    for year in sorted(by_year):
        cells = table.add_row().cells
        cells[0].text = str(year)
        rows_by_partner = {r['Partner']: r for _, r in by_year[year].iterrows()}
        for idx, (partner, col, _) in enumerate(col_specs, start=1):
            row = rows_by_partner.get(partner)
            cells[idx].text = _format_number(row[col], 3) if row is not None else ''
    _style_table(table)


def _write_word(df: pd.DataFrame, anomalies: pd.DataFrame,
                chapters: tuple[str, ...], year_min: int, year_max: int,
                export_dir: Path, log: logging.Logger) -> Path:
    from docx import Document

    document = Document()
    _apply_page_layout(document)

    document.add_heading(
        f'HS2 Cij by weighting scheme — US and China, {year_min}-{year_max}',
        level=1,
    )
    document.add_paragraph(
        "Cij_Drysdale = Σ_k RCA_x_k · RCA_m_k · (W_k/W);   "
        "Cij(world-wt) = RCA_x_HS2 × RCA_m_HS2, weights ∝ W_k;   "
        "Cij(own-wt) = RCA_x_HS2 × RCA_m_HS2, export weights ∝ X_ik, import weights ∝ M_jk;   "
        "RCA_x_k = (X_ik/X_i) ÷ (W_k/W),  RCA_m_k = (M_jk/M_j) ÷ (W_k/W)"
    )

    for country in sorted(df['Country'].unique()):
        for chapter in chapters:
            frame = df[(df['Country'] == country) & (df['HS2'] == chapter)]
            if not frame.empty:
                _add_reporter_chapter_table(document, country, chapter, frame)

    document.add_heading('Data notes', level=2)
    if anomalies.empty:
        document.add_paragraph(
            "Data quality: every (reporter, partner, year, chapter) group's "
            "own-share weights sum to 1.000 on both the export and import side — "
            "no HS6 lines dropped when matching trade to world exports."
        )
    else:
        para = document.add_paragraph()
        run = para.add_run(
            f"Data quality WARNING: {len(anomalies)} group(s) have own-share "
            "weights that do not sum to 1.0 — some HS6 lines had no matching "
            "world-export row and were dropped. Affected:")
        run.bold = True
        for _, r in anomalies.iterrows():
            document.add_paragraph(
                f"{int(r['Year'])} · {r['Country']} · {r['Partner']} · HS {r['HS2']}: "
                f"Σw_x={r['wcheck_x']:.4f}, Σw_m={r['wcheck_m']:.4f}",
                style='List Bullet',
            )
    document.add_paragraph(DATA_SOURCE_TEXT)

    output_path = export_dir / 'Cij_Weighting_Comparison.docx'
    document.save(output_path)
    log.info("Wrote %s.", output_path)
    return output_path


# ── entry point ─────────────────────────────────────────────────────────────

def export_cij_comparison(
    export_dir: Path,
    chapters: tuple[str, ...] = DEFAULT_CHAPTERS,
    year_min: int = 2001,
    year_max: int = 2024,
    countries: list[str] | None = None,
    log: logging.Logger | None = None,
) -> tuple[Path, Path, pd.DataFrame]:
    """Compute and write the Cij weighting-comparison Excel + Word deliverables.

    Returns (excel_path, word_path, anomalies_df). A non-empty anomalies_df
    means at least one group's own-share weights did not sum to 1.0; the caller
    should surface a warning (files are still written)."""
    log = log or logging.getLogger(__name__)
    export_dir.mkdir(parents=True, exist_ok=True)

    chapters = tuple(str(c).zfill(2) for c in chapters)
    df = compute_cij_comparison(chapters, year_min, year_max)
    if countries:
        df = df[df['Country'].isin(countries)]
    anomalies = detect_weight_anomalies(df)

    excel_path = _write_excel(df, anomalies, chapters, export_dir, log)
    word_path = _write_word(df, anomalies, chapters, year_min, year_max,
                            export_dir, log)
    return excel_path, word_path, anomalies

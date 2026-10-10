"""
Importer-weighted RCA deliverable (configurable HS tier).

Implements the professor's weighted-average RCA at an HS tier (HS2 chapter by
default, HS4 heading when ``digits=4``):

    RCA_tier(j) = Σ_k  w_k · RCA_import_k

where the sum runs over the HS6 products k inside the tier, RCA_import_k is the
importer's Balassa RCA for that HS6 line — (M_jk/M_j) ÷ (W_k/W), benchmarked
against world *exports* for consistency — and the weight w_k is the importer's
own within-tier trade share:

    w_k = M_jk / Σ_k M_jk          (Σ_k w_k = 1 by construction)

This is a genuinely different number from the pipeline's canonical RCA (the
aggregate ratio of summed shares, (ΣM_k/M_j)÷(ΣW_k/W)); this one is the
share-weighted *mean of the per-HS6 RCAs*, which is what the professor asked for.

The computation is the raw SQL the analysis was prototyped in, run through the
Django DB connection so Excel + Word come straight from the same query.

Deliverables (default folder `data/TradeMapData/export/weighted_rca/`):
  - `Weighted_RCA_{tier}.xlsx` — `Weighted RCA` (long), one pivot sheet per
    partner (rows=year, cols=tier code), and a `Data Quality` sheet flagging any
    group whose weights do not sum to 1.0.
  - `Weighted_RCA_{tier}.docx` — report-ready table per partner + method/data note.
  where {tier} is 'HS2' (digits=2) or 'HS4' (digits=4).

Data quality: `weight_check = Σ_k w_k` must equal 1.0 for every (year, partner,
tier). It drops below 1.0 only if an HS6 line the importer trades has no matching
world-export row that year (inner join), so those weights no longer span the
tier. The command **warns** and writes a Data Quality section but still produces
the files — the report author decides whether to use a flagged year.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .rca_only import CHAPTER_LABELS, STRATEGIC_CHAPTERS
from .word_summary import _apply_page_layout, _format_number, _style_table

DATA_SOURCE_TEXT = 'Data source: Calculated from the World Trade Map.'
WEIGHT_TOLERANCE = 1e-6  # |Σ w_k − 1| above this flags the group

# Default tier codes (the 10 strategic HS2 chapters). Overridable from the CLI.
DEFAULT_CHAPTERS = STRATEGIC_CHAPTERS  # ('28','29','30','38','84','85','87','88','90','93')


def _build_sql(digits: int) -> str:
    """Weighted-import-RCA query, grouping HS6 to a tier of `digits` characters.
    The tier IN-list and year bounds are bound as parameters (`%(codes)s`, `%%s`);
    `digits` is inlined (trusted int). Mirrors the prototype query: world-export
    shares as the RCA benchmark, importer within-tier share as the weight."""
    d = int(digits)
    return f"""
WITH TOTAL AS (
    SELECT year, value_usd_thousands AS TOTAL_USD_THOUSANDS
    FROM loadFiles_worldexport
    WHERE product_code = 'TOTAL'
), HS6_WORLD_TOTAL AS (
    SELECT year, product_code HS6, SUBSTR(product_code, 1, {d}) TIER,
           value_usd_thousands AS HS6_TOTAL_US_THOUSANDS
    FROM loadFiles_worldexport
    WHERE product_code <> 'TOTAL'
), TOTAL_WORLD_TRADE AS (
    SELECT a.year, a.TOTAL_USD_THOUSANDS,
           b.HS6, b.TIER, b.HS6_TOTAL_US_THOUSANDS,
           CAST(b.HS6_TOTAL_US_THOUSANDS AS REAL) / a.TOTAL_USD_THOUSANDS HS6_WORLD_PROP
    FROM TOTAL a JOIN HS6_WORLD_TOTAL b ON a.year = b.year
), IMPORT_TOTAL AS (
    SELECT year, partner, value_usd_thousands TOTAL_USD_THOUSANDS
    FROM loadFiles_partnerimportfromworld WHERE product_code = 'TOTAL'
), HS6_IMPORT_TOTAL AS (
    -- value_usd_thousands > 0: count/weight only products the partner actually
    -- imported that year. Zero/NULL-value rows carry weight 0 and never enter
    -- the weighted average, so dropping them changes only n, not the RCA.
    SELECT year, partner, product_code HS6, SUBSTR(product_code, 1, {d}) TIER,
           value_usd_thousands HS6_TOTAL_US_THOUSANDS
    FROM loadFiles_partnerimportfromworld
    WHERE product_code <> 'TOTAL' AND value_usd_thousands > 0
), TIER_IMPORT_TOTAL AS (
    SELECT year, partner, SUBSTR(product_code, 1, {d}) TIER,
           SUM(value_usd_thousands) TIER_TOTAL_US_THOUSANDS
    FROM loadFiles_partnerimportfromworld WHERE product_code <> 'TOTAL'
    GROUP BY year, partner, SUBSTR(product_code, 1, {d})
), TOTAL_IMPORT_TRADE AS (
    SELECT a.year, a.partner, a.TOTAL_USD_THOUSANDS,
           b.HS6, b.TIER, b.HS6_TOTAL_US_THOUSANDS, c.TIER_TOTAL_US_THOUSANDS,
           CAST(b.HS6_TOTAL_US_THOUSANDS AS REAL) / a.TOTAL_USD_THOUSANDS HS6_PARTNER_PROP,
           CAST(b.HS6_TOTAL_US_THOUSANDS AS REAL) / c.TIER_TOTAL_US_THOUSANDS HS6_WITHIN_TIER_WEIGHT
    FROM IMPORT_TOTAL a
    JOIN HS6_IMPORT_TOTAL b ON a.year = b.year AND a.partner = b.partner
    JOIN TIER_IMPORT_TOTAL c ON a.year = c.year AND a.partner = c.partner AND b.TIER = c.TIER
), RCA_IMPORT_HS6 AS (
    SELECT a.year, a.partner, a.TIER, a.HS6, a.HS6_WITHIN_TIER_WEIGHT,
           CAST(a.HS6_PARTNER_PROP AS REAL) / b.HS6_WORLD_PROP RCA_IMPORT_HS6
    FROM TOTAL_IMPORT_TRADE a
    JOIN TOTAL_WORLD_TRADE b ON a.year = b.year AND a.HS6 = b.HS6
), RCA_IMPORT_TIER_WEIGHTED AS (
    SELECT year, partner, TIER,
           SUM(HS6_WITHIN_TIER_WEIGHT * RCA_IMPORT_HS6) RCA_IMPORT_WEIGHTED,
           SUM(HS6_WITHIN_TIER_WEIGHT) weight_check,
           COUNT(*) n_hs6_lines
    FROM RCA_IMPORT_HS6 GROUP BY year, partner, TIER
)
SELECT year, partner, TIER, RCA_IMPORT_WEIGHTED, weight_check, n_hs6_lines
FROM RCA_IMPORT_TIER_WEIGHTED
WHERE TIER IN (%(codes)s)
  AND year BETWEEN %%s AND %%s
ORDER BY partner, TIER, year
"""


def compute_weighted_import_rca(
    codes: tuple[str, ...] = DEFAULT_CHAPTERS,
    year_min: int = 2001,
    year_max: int = 2024,
    digits: int = 2,
) -> pd.DataFrame:
    """Run the weighted-RCA query and return a long DataFrame with columns
    Year, Partner, Tier, RCA_Import_Weighted, weight_check, n_hs6_lines."""
    from django.db import connection

    codes = tuple(str(c).zfill(digits) for c in codes)
    if not all(c.isdigit() and len(c) == digits for c in codes):
        raise ValueError(f"codes must be {digits}-digit strings, got {codes!r}")

    placeholders = ', '.join(['%s'] * len(codes))
    sql = _build_sql(digits) % {'codes': placeholders}
    params = [*codes, year_min, year_max]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    df = pd.DataFrame(rows, columns=columns)
    df = df.rename(columns={
        'year': 'Year', 'partner': 'Partner', 'TIER': 'Tier',
        'RCA_IMPORT_WEIGHTED': 'RCA_Import_Weighted',
    })
    df['Year'] = df['Year'].astype(int)
    return df


def detect_weight_anomalies(df: pd.DataFrame,
                            tolerance: float = WEIGHT_TOLERANCE) -> pd.DataFrame:
    """Rows whose within-tier weights do not sum to 1.0 (lines dropped by the
    world-export join). Empty frame means every group is clean."""
    flagged = df[(df['weight_check'] - 1.0).abs() > tolerance].copy()
    flagged['weight_shortfall'] = 1.0 - flagged['weight_check']
    return flagged.sort_values(['Partner', 'Tier', 'Year'])


# ── pivots ────────────────────────────────────────────────────────────────

def _pivot_for_partner(df: pd.DataFrame, partner: str,
                       codes: tuple[str, ...]) -> pd.DataFrame:
    """rows=Year, cols=tier code, values=RCA_Import_Weighted."""
    frame = df[df['Partner'] == partner]
    return (
        frame.pivot(index='Year', columns='Tier', values='RCA_Import_Weighted')
        .reindex(columns=list(codes))
        .sort_index()
    )


def _n_pivot_for_partner(df: pd.DataFrame, partner: str,
                         codes: tuple[str, ...]) -> pd.DataFrame:
    """rows=Year, cols=tier code, values=n_hs6_lines — the count of HS6 products
    the partner actually imported in that tier that year (varies year to year)."""
    frame = df[df['Partner'] == partner]
    return (
        frame.pivot(index='Year', columns='Tier', values='n_hs6_lines')
        .reindex(columns=list(codes))
        .sort_index()
    )


# ── Excel ─────────────────────────────────────────────────────────────────

def _write_excel(df: pd.DataFrame, anomalies: pd.DataFrame,
                 codes: tuple[str, ...], labels: dict[str, str], tier_name: str,
                 export_dir: Path, log: logging.Logger) -> Path:
    output_path = export_dir / f'Weighted_RCA_{tier_name}.xlsx'
    partners = sorted(df['Partner'].unique())

    long_sheet = df.copy()
    long_sheet[tier_name] = long_sheet['Tier']
    long_sheet['Label'] = long_sheet['Tier'].map(labels).fillna('')
    long_sheet = long_sheet[['Year', 'Partner', tier_name, 'Label',
                             'RCA_Import_Weighted', 'weight_check', 'n_hs6_lines']]

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        long_sheet.to_excel(writer, sheet_name='Weighted RCA', index=False)
        for partner in partners:
            pivot = _pivot_for_partner(df, partner, codes)
            pivot.columns = [f"{c} {labels.get(c, '')}".strip() for c in pivot.columns]
            pivot.to_excel(writer, sheet_name=f"RCA - {partner}"[:31])

        if anomalies.empty:
            dq = pd.DataFrame(
                [{'Status': 'OK',
                  'Note': f'All within-{tier_name} weights sum to 1.0 '
                          '(no HS6 lines dropped by the world-export join).'}]
            )
        else:
            dq = anomalies[['Year', 'Partner', 'Tier', 'weight_check',
                            'weight_shortfall', 'n_hs6_lines',
                            'RCA_Import_Weighted']].rename(columns={'Tier': tier_name})
            dq.insert(0, 'Status', 'CHECK')
        dq.to_excel(writer, sheet_name='Data Quality', index=False)

    log.info("Wrote %s (%d rows, %d flagged).",
             output_path, len(df), len(anomalies))
    return output_path


# ── Word ──────────────────────────────────────────────────────────────────

def _add_partner_table(document, partner: str, pivoted: pd.DataFrame,
                       n_pivot: pd.DataFrame, codes: tuple[str, ...],
                       labels: dict[str, str]) -> None:
    document.add_heading(partner, level=2)
    table = document.add_table(rows=1, cols=1 + len(codes))
    table.style = 'Light Grid Accent 1'
    header = table.rows[0].cells
    header[0].text = 'Year'
    for col_index, code in enumerate(codes, start=1):
        header[col_index].text = f"HS {code}\n{labels.get(code, '')}"
    for year, row in pivoted.iterrows():
        cells = table.add_row().cells
        cells[0].text = str(int(year))
        n_row = n_pivot.loc[year] if year in n_pivot.index else None
        for col_index, code in enumerate(codes, start=1):
            value = _format_number(row.get(code), 3)
            n = None if n_row is None else n_row.get(code)
            if value and n is not None and not pd.isna(n):
                value = f"{value} (n={int(n)})"
            cells[col_index].text = value
    _style_table(table)


def _add_method_description(document, tier_name: str, tier_noun: str) -> None:
    """Formula block + a 'Where' definition list, tier-aware (K = HS2 chapter or
    HS4 heading). World benchmark written as T (= world exports), the importer's
    own within-tier share as the weight."""
    digit_word = '2-digit' if tier_name == 'HS2' else '4-digit'
    unit = tier_noun.split()[-1]              # 'chapter' or 'heading'
    units = unit + 's'

    for line in (
        f"RCA({tier_name}) = Σ_(k in K) w_k · RCA_k",
        "w_k = M_jk / M_jK",
        "RCA_k = (M_jk / M_j) ÷ (T_k / T)",
    ):
        p = document.add_paragraph()
        p.add_run(line).bold = True

    document.add_paragraph("Where:")
    definitions = [
        ("K", f"HS {digit_word} {unit}"),
        ("k", f"HS 6-digit product belonging to {unit} K"),
        ("j", "partner country (US or China)"),
        ("M_jk", "partner j's imports of product k from the world"),
        ("M_jK", f"partner j's total imports of {unit} K (= Σ_(k in K) M_jk)"),
        ("M_j", f"partner j's total imports from the world (all {units})"),
        ("T_k", "world total exports of product k"),
        ("T", "world total exports across all products"),
        ("RCA_k", "HS6-level Balassa RCA for product k"),
        ("w_k", f"HS6 product k's share of {unit} K in partner j's imports"),
        ("n", f"number of HS6 products in {unit} K that partner j imported that "
              "year (positive value) and that enter the weighted average; shown "
              "beside each value; varies year to year"),
    ]
    for symbol, meaning in definitions:
        p = document.add_paragraph(style='List Bullet')
        p.add_run(f"{symbol}").bold = True
        p.add_run(f" = {meaning}")


def _add_combined_table(document, df: pd.DataFrame, codes: tuple[str, ...],
                        labels: dict[str, str]) -> None:
    """One table with both partners side by side: a two-row header (partner
    spanning its tier codes on top, 'HS {code} {label}' beneath), then one row
    per year with `value (n=..)` cells. Used when the tier has few codes."""
    partners = sorted(df['Partner'].unique())
    pivots = {p: _pivot_for_partner(df, p, codes) for p in partners}
    n_pivots = {p: _n_pivot_for_partner(df, p, codes) for p in partners}

    n_cols = 1 + len(partners) * len(codes)
    table = document.add_table(rows=2, cols=n_cols)
    table.style = 'Light Grid Accent 1'

    top, sub = table.rows[0].cells, table.rows[1].cells
    top[0].merge(sub[0]).text = 'Year'          # Year header spans both rows
    col = 1
    for partner in partners:
        group = top[col] if len(codes) == 1 else top[col].merge(top[col + len(codes) - 1])
        group.text = partner
        for j, code in enumerate(codes):
            sub[col + j].text = f"HS {code}\n{labels.get(code, '')}".strip()
        col += len(codes)

    years = sorted({int(y) for p in partners for y in pivots[p].index})
    for year in years:
        cells = table.add_row().cells
        cells[0].text = str(year)
        col = 1
        for partner in partners:
            rca_row = pivots[partner].loc[year] if year in pivots[partner].index else None
            n_row = n_pivots[partner].loc[year] if year in n_pivots[partner].index else None
            for code in codes:
                value = _format_number(rca_row.get(code), 3) if rca_row is not None else ''
                n = None if n_row is None else n_row.get(code)
                if value and n is not None and not pd.isna(n):
                    value = f"{value} (n={int(n)})"
                cells[col].text = value
                col += 1
    _style_table(table)
    # _style_table only bolds row 0; bold the second (code) header row too.
    from docx.shared import Pt
    for cell in table.rows[1].cells:
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.bold = True
                run.font.size = Pt(8.5)


def _write_word(df: pd.DataFrame, anomalies: pd.DataFrame,
                codes: tuple[str, ...], labels: dict[str, str], tier_name: str,
                tier_noun: str, year_min: int, year_max: int,
                export_dir: Path, log: logging.Logger,
                combine_partners: bool = False) -> Path:
    from docx import Document

    document = Document()
    _apply_page_layout(document)

    document.add_heading(
        f'Importer-weighted RCA by {tier_noun} for the US and China, '
        f'{year_min}-{year_max}',
        level=1,
    )
    _add_method_description(document, tier_name, tier_noun)
    if combine_partners and df['Partner'].nunique() >= 2:
        _add_combined_table(document, df, codes, labels)
    else:
        for partner in sorted(df['Partner'].unique()):
            pivoted = _pivot_for_partner(df, partner, codes)
            n_pivot = _n_pivot_for_partner(df, partner, codes)
            _add_partner_table(document, partner, pivoted, n_pivot, codes, labels)

    document.add_heading('Data notes', level=2)
    if anomalies.empty:
        document.add_paragraph(
            f"Data quality: every (year, partner, {tier_noun}) group's weights "
            "sum to 1.000 — no HS6 lines were dropped when matching importer "
            "trade to world exports, so each weighted average spans the full "
            f"{tier_noun}."
        )
    else:
        para = document.add_paragraph()
        run = para.add_run(
            f"Data quality WARNING: {len(anomalies)} group(s) have weights that "
            "do not sum to 1.0 — some HS6 lines the importer trades had no "
            "matching world-export row that year and were dropped. Affected:"
        )
        run.bold = True
        for _, r in anomalies.iterrows():
            document.add_paragraph(
                f"{int(r['Year'])} · {r['Partner']} · HS {r['Tier']}: "
                f"Σw = {r['weight_check']:.4f} "
                f"(shortfall {r['weight_shortfall']:.4f}, n={int(r['n_hs6_lines'])})",
                style='List Bullet',
            )
    document.add_paragraph(DATA_SOURCE_TEXT)

    output_path = export_dir / f'Weighted_RCA_{tier_name}.docx'
    document.save(output_path)
    log.info("Wrote %s.", output_path)
    return output_path


# ── Charts (black & white friendly) ─────────────────────────────────────────

# Distinct marker shapes + line styles so sectors are told apart in greyscale
# print (no reliance on colour). Distinct markers alone guarantee uniqueness;
# the line-style cycle adds a second visual cue.
_MARKERS = ['o', 's', '^', 'D', 'v', 'P', 'X', '*', '>', '<', 'h', 'p']
_LINESTYLES = ['-', '--', '-.', ':']


def _write_charts(df: pd.DataFrame, codes: tuple[str, ...], labels: dict[str, str],
                  tier_name: str, export_dir: Path, log: logging.Logger) -> list[Path]:
    """One PNG per partner: importer-weighted RCA vs year, one line per sector,
    each sector a distinct black marker + line style (greyscale-print safe)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    paths: list[Path] = []
    for partner in sorted(df['Partner'].unique()):
        pivot = _pivot_for_partner(df, partner, codes)
        fig, ax = plt.subplots(figsize=(12, 6))
        data_max = 1.0
        for i, code in enumerate(codes):
            if code not in pivot.columns:
                continue
            series = pivot[code].dropna()
            if series.empty:
                continue
            data_max = max(data_max, float(series.max()))
            ax.plot(
                series.index, series.values,
                color='black',
                marker=_MARKERS[i % len(_MARKERS)],
                linestyle=_LINESTYLES[i % len(_LINESTYLES)],
                markersize=5, linewidth=1.2, markerfacecolor='white',
                label=f"HS {code} — {labels.get(code, '')}".strip(' —'),
            )
        ax.axhline(1, linestyle=(0, (1, 1)), color='grey', linewidth=1)
        ax.set_title(f"Importer-weighted RCA — {partner} ({tier_name})")
        ax.set_xlabel('Year')
        ax.set_ylabel('RCA (import)')
        years = sorted(int(y) for y in pivot.index)
        if years:
            ax.set_xticks(range(years[0], years[-1] + 1, 2))
            ax.set_xlim(years[0], years[-1])
        # Headroom above the highest point so the latest (right-edge) values are
        # never clipped at the frame; bottom stays autoscaled.
        ax.set_ylim(bottom=0, top=data_max * 1.12)
        ax.tick_params(axis='x', rotation=45)
        # 'best' lets matplotlib pick the corner with least overlap, so the
        # legend never sits on the data (e.g. the 2023-24 rise in US HS 8541).
        ax.legend(title=f'{tier_name} sector', loc='best',
                  fontsize=8, framealpha=0.9)
        fig.text(0.01, 0.01, DATA_SOURCE_TEXT, fontsize=8, style='italic')
        fig.tight_layout(rect=[0, 0.03, 1, 1])
        out = export_dir / f"Weighted_RCA_{tier_name}_{partner}.png"
        fig.savefig(out, dpi=130, bbox_inches='tight')
        plt.close(fig)
        paths.append(out)
    log.info("Wrote %d weighted-RCA charts.", len(paths))
    return paths


def _write_combined_chart(df: pd.DataFrame, codes: tuple[str, ...],
                          labels: dict[str, str], tier_name: str,
                          export_dir: Path, log: logging.Logger) -> Path:
    """One PNG overlaying every (partner, sector): marker shape per sector,
    line style per partner (e.g. China solid, US dashed), all black for
    greyscale print."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    partners = sorted(df['Partner'].unique())
    fig, ax = plt.subplots(figsize=(12, 6))
    data_max = 1.0
    for pi, partner in enumerate(partners):
        pivot = _pivot_for_partner(df, partner, codes)
        for ci, code in enumerate(codes):
            if code not in pivot.columns:
                continue
            series = pivot[code].dropna()
            if series.empty:
                continue
            data_max = max(data_max, float(series.max()))
            ax.plot(
                series.index, series.values, color='black',
                marker=_MARKERS[ci % len(_MARKERS)],
                linestyle=_LINESTYLES[pi % len(_LINESTYLES)],
                markersize=5, linewidth=1.2, markerfacecolor='white',
                label=f"{partner} — HS {code} {labels.get(code, '')}".strip(),
            )
    ax.axhline(1, linestyle=(0, (1, 1)), color='grey', linewidth=1)
    ax.set_title(f"Importer-weighted RCA — {tier_name} ({' & '.join(partners)})")
    ax.set_xlabel('Year')
    ax.set_ylabel('RCA (import)')
    years = sorted({int(y) for p in partners for y in _pivot_for_partner(df, p, codes).index})
    if years:
        ax.set_xticks(range(years[0], years[-1] + 1, 2))
        ax.set_xlim(years[0], years[-1])
    ax.set_ylim(bottom=0, top=data_max * 1.12)
    ax.tick_params(axis='x', rotation=45)
    ax.legend(title='Partner — sector', loc='best', fontsize=8, framealpha=0.9)
    fig.text(0.01, 0.01, DATA_SOURCE_TEXT, fontsize=8, style='italic')
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    out = export_dir / f"Weighted_RCA_{tier_name}_combined.png"
    fig.savefig(out, dpi=130, bbox_inches='tight')
    plt.close(fig)
    log.info("Wrote %s (combined partners).", out)
    return out


# ── entry point ─────────────────────────────────────────────────────────────

def export_weighted_rca(
    export_dir: Path,
    codes: tuple[str, ...] = DEFAULT_CHAPTERS,
    year_min: int = 2001,
    year_max: int = 2024,
    digits: int = 2,
    labels: dict[str, str] | None = None,
    tier_name: str | None = None,
    log: logging.Logger | None = None,
) -> tuple[Path, Path, list[Path], pd.DataFrame]:
    """Compute and write the weighted-RCA Excel + Word + charts for the given HS
    tier (`digits` = 2 → HS2 chapters, 4 → HS4 headings).

    Returns (excel_path, word_path, chart_paths, anomalies_df). A non-empty
    anomalies_df means at least one group's weights did not sum to 1.0; the
    caller should surface a warning (files are still written)."""
    log = log or logging.getLogger(__name__)
    export_dir.mkdir(parents=True, exist_ok=True)

    tier_name = tier_name or f'HS{digits}'
    tier_noun = {'HS2': 'HS2 chapter', 'HS4': 'HS4 heading'}.get(tier_name, tier_name)
    labels = labels if labels is not None else CHAPTER_LABELS

    codes = tuple(str(c).zfill(digits) for c in codes)
    df = compute_weighted_import_rca(codes, year_min, year_max, digits)
    anomalies = detect_weight_anomalies(df)

    # Put both partners in one table when the tier has few codes (e.g. HS4
    # 8541/8542); keep wide scopes (HS2 chapters) as separate per-partner tables.
    combine_partners = len(codes) <= 6

    excel_path = _write_excel(df, anomalies, codes, labels, tier_name, export_dir, log)
    word_path = _write_word(df, anomalies, codes, labels, tier_name,
                            tier_noun, year_min, year_max, export_dir, log,
                            combine_partners=combine_partners)
    chart_paths = _write_charts(df, codes, labels, tier_name, export_dir, log)
    if combine_partners and df['Partner'].nunique() >= 2:
        chart_paths.append(
            _write_combined_chart(df, codes, labels, tier_name, export_dir, log))
    return excel_path, word_path, chart_paths, anomalies

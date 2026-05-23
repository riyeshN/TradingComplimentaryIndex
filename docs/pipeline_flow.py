"""
Generate docs/pipeline_flow.png — a block diagram of the TCI pipeline.

Run with:
    conda run -n Econometrics_Deps python docs/pipeline_flow.py

Source kept in repo so the diagram stays in sync with the modules it describes.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt


SOURCE_COLOR  = "#fde7c5"   # ingestion / inputs
DATA_COLOR    = "#d9eaff"   # data assembly
MATH_COLOR    = "#dff5e0"   # math / indicators
EXPORT_COLOR  = "#f4ddff"   # exports
TEXT_COLOR    = "#1f2330"
EDGE_COLOR    = "#5b6376"


def draw_box(ax, x, y, w, h, text, color, fontsize=9):
    box = patches.FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1.0, edgecolor=EDGE_COLOR, facecolor=color,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text,
            ha="center", va="center", fontsize=fontsize, color=TEXT_COLOR)


def draw_arrow(ax, x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=EDGE_COLOR, lw=1.0))


def main():
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 8)
    ax.set_aspect("equal")
    ax.axis("off")

    # Row 1 — ingestion
    draw_box(ax, 0.4, 6.6, 2.5, 0.9,
             "TradeMap TSV files\n(data/TradeMapData/data/)", SOURCE_COLOR)
    draw_box(ax, 4.3, 6.6, 2.4, 0.9,
             "Django models\n(5 trade tables)", SOURCE_COLOR)

    # Row 2 — assembly
    draw_box(ax, 4.3, 5.2, 2.4, 0.9,
             "trade_data_loader\nload_all()", DATA_COLOR)

    # Row 3 — filter + HS6 indicators
    draw_box(ax, 4.3, 3.9, 2.4, 0.85,
             "_filter_by_scope_and_year()", DATA_COLOR, fontsize=8.5)
    draw_box(ax, 1.0, 2.6, 3.0, 0.95,
             "_calculate_tci_drysdale_garnaut()\n→ TCI_Drysdale_Garnaut", MATH_COLOR, fontsize=8.5)
    draw_box(ax, 7.0, 2.6, 3.0, 0.95,
             "_calculate_rca_and_tci_rca()\n→ RCA × 2, DG decomposition", MATH_COLOR, fontsize=8.5)

    # Row 4 — aggregation
    draw_box(ax, 1.0, 1.2, 3.0, 0.95,
             "_aggregate_hs6_to_hs4()\n+ _aggregate_hs4_to_hs2() if HS2 scope", MATH_COLOR, fontsize=8.5)
    draw_box(ax, 7.0, 1.2, 3.0, 0.95,
             "_calculate_headline_cij()\nHeadline = ΣHS6 Cij over scope", MATH_COLOR, fontsize=8.5)

    # Row 5 — exporters
    draw_box(ax, 0.2, 0.1, 2.4, 0.7, "exporters/excel.py\n{partner}_TCI.xlsx — scope subdir",
             EXPORT_COLOR, fontsize=8)
    draw_box(ax, 4.3, 0.1, 2.4, 0.7, "exporters/charts.py\n{partner}_{tier}_TCI_DG.png",
             EXPORT_COLOR, fontsize=8)
    draw_box(ax, 8.4, 0.1, 2.4, 0.7, "exporters/word_summary.py\nRCA_Cij_Summary.docx",
             EXPORT_COLOR, fontsize=8)

    # Arrows
    draw_arrow(ax, 2.9, 7.05, 4.3, 7.05)                            # TSV → models
    draw_arrow(ax, 5.5, 6.6, 5.5, 6.1)                              # models → loader
    draw_arrow(ax, 5.5, 5.2, 5.5, 4.75)                             # loader → filter
    draw_arrow(ax, 5.0, 3.9, 2.7, 3.55)                             # filter → DG
    draw_arrow(ax, 6.0, 3.9, 8.5, 3.55)                             # filter → RCA
    draw_arrow(ax, 2.5, 2.6, 2.5, 2.15)                             # DG → HS4 agg
    draw_arrow(ax, 8.5, 2.6, 8.5, 2.15)                             # RCA → headline
    draw_arrow(ax, 4.0, 1.6, 7.0, 1.6)                              # HS4 agg → headline (shared via instance state)
    draw_arrow(ax, 1.6, 1.2, 1.6, 0.8)                              # HS4 agg → excel (also reads HS6 + headline state)
    draw_arrow(ax, 3.6, 1.2, 5.0, 0.8)                              # HS4 agg → charts
    draw_arrow(ax, 3.9, 1.45, 8.4, 0.7)                             # HS4 agg → word summary (reads HS4 index)

    # Legend
    legend_y = 7.4
    for i, (label, color) in enumerate([
        ("Ingestion", SOURCE_COLOR),
        ("Data assembly", DATA_COLOR),
        ("Indicators (pure math)", MATH_COLOR),
        ("Exporters", EXPORT_COLOR),
    ]):
        x = 7.6
        y = legend_y - i * 0.25
        ax.add_patch(patches.Rectangle((x, y), 0.18, 0.16,
                                       edgecolor=EDGE_COLOR, facecolor=color, lw=1.0))
        ax.text(x + 0.24, y + 0.08, label, fontsize=8, va="center", color=TEXT_COLOR)

    ax.set_title("TCI Pipeline — Data Flow", fontsize=12, color=TEXT_COLOR, pad=10)

    out = Path(__file__).parent / "pipeline_flow.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

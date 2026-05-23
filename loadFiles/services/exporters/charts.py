"""
HS4 Cij time-series charts — one PNG per (partner, HS4) heading.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from ._filter import tier_suffix



def export_hs4_tci_charts(
    tier_index_by_partner: dict[str, pd.DataFrame],
    export_dir: Path,
    tier_column: str = 'HS4',
    countries: list[str] | None = None,
    tier_codes: list[str] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Plot primary-tier Cij time series by reporter — one PNG per (partner, tier code)."""
    log = logger or logging.getLogger(__name__)
    export_dir.mkdir(parents=True, exist_ok=True)

    tci_column = f'TCI_DG_{tier_suffix(tier_column)}'

    for partner_name, tier_data in tier_index_by_partner.items():
        data = tier_data.copy()
        if countries is not None:
            data = data[data['Country'].isin(countries)]
        if tier_codes is not None:
            data = data[data[tier_column].isin(tier_codes)]
        data['Year'] = pd.to_numeric(data['Year'], errors='coerce')
        data = data.dropna(subset=['Year', tci_column]).sort_values('Year')

        for tier_code in data[tier_column].unique():
            tier_rows = data[data[tier_column] == tier_code]
            fig, ax = plt.subplots(figsize=(12, 6))
            for country_name in sorted(tier_rows['Country'].unique()):
                country_rows = tier_rows[tier_rows['Country'] == country_name]
                ax.plot(country_rows['Year'], country_rows[tci_column],
                        marker='o', label=country_name)
            ax.set_title(
                f'Trade Complementarity Index — {tier_column} {tier_code} — Partner: {partner_name}'
            )
            ax.set_xlabel('Year')
            ax.set_ylabel('TCI (Drysdale-Garnaut, sum of HS6)')
            ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            ax.grid(True, linestyle='--', alpha=0.5)
            fig.tight_layout()
            fig.savefig(export_dir / f"{partner_name}_{tier_code}_TCI_DG.png")
            plt.close(fig)

    log.info("%s TCI charts exported.", tier_column)

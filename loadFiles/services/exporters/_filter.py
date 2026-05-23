"""Shared helpers used by all exporters."""

from __future__ import annotations

import pandas as pd

# Maps a primary-tier code column to the column-name suffix the pipeline uses
# for that tier's metrics (e.g. HS4 → 'TCI_DG_4digit', SITC → 'TCI_DG_sitc').
_TIER_SUFFIX = {'HS2': '2digit', 'HS4': '4digit', 'SITC': 'sitc'}


def tier_suffix(tier_column: str) -> str:
    """Column-name suffix for a primary tier ('4digit', '2digit', or 'sitc')."""
    return _TIER_SUFFIX.get(tier_column, '4digit')


def filter_scope(
    df: pd.DataFrame,
    countries: list[str] | None,
    hs4_codes: list[str] | None,
) -> pd.DataFrame:
    """Apply Country and HS4 filters. Each filter is skipped when None."""
    if countries is not None:
        df = df[df['Country'].isin(countries)]
    if hs4_codes is not None:
        df = df[df['HS4'].isin(hs4_codes)]
    return df

"""
Reads the five trade tables from the database and assembles, per partner, a
long-format DataFrame with one row per (reporter, year, HS6 product). No
indicator math here — that lives in TCICalculator.

Each merged row carries the trade values needed downstream:
  - Reporter Export To Partner / World
  - Partner Import From World
  - World Export of item k
  - Reporter / Partner / World per-year totals (denominators)
  - World Export HS4 Total (reporter-independent HS4 denominator)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class LoadedTradeData:
    """Bundle returned by load_all() — long-format per-partner frames plus
    reporter-independent precomputed HS-tier totals and TOTAL-row denominators."""
    hs6_per_partner:     dict[str, pd.DataFrame]
    world_hs4_totals:    pd.DataFrame
    partner_hs4_totals:  pd.DataFrame
    reporter_hs4_totals: pd.DataFrame
    world_hs2_totals:    pd.DataFrame
    partner_hs2_totals:  pd.DataFrame
    reporter_hs2_totals: pd.DataFrame
    world_sitc_totals:    pd.DataFrame  # by (SITC section, Year); empty if no concordance
    partner_sitc_totals:  pd.DataFrame  # by (partner, SITC section, Year)
    reporter_sitc_totals: pd.DataFrame  # by (Country, SITC section, Year)
    reporter_totals:     pd.DataFrame   # X_i, by (Country, Year)
    partner_totals:      pd.DataFrame   # M_j, by (partner, Year)
    world_totals:        pd.DataFrame   # W, by (Year)

_RENAMES = {
    'bilateral': {
        'reporter': 'Country',
        'product_code': 'Product code',
        'year': 'Year',
        'value_usd_thousands': 'Reporter Export To Partner',
    },
    'reporter_world': {
        'reporter': 'Country',
        'product_code': 'Product code',
        'year': 'Year',
        'value_usd_thousands': 'Reporter Export To World',
    },
    'partner_import': {
        'product_code': 'Product code',
        'year': 'Year',
        'value_usd_thousands': 'Partner Import From World',
    },
    'world_export': {
        'product_code': 'Product code',
        'year': 'Year',
        'value_usd_thousands': 'World Export of item k',
    },
}

_FINAL_COLUMNS = [
    'Country', 'Year', 'Product code', 'Product label',
    'Reporter Export To Partner',
    'Reporter Export To World',
    'Partner Import From World',
    'World Export of item k',
    "Reporter's Total Export To World",
    "Partner's Total Import From World",
    'Total World Export',
    'World Export HS4 Total',
]


def _is_total(series: pd.Series) -> pd.Series:
    return series.astype(str).str.upper() == 'TOTAL'


def _query_long_format() -> dict[str, pd.DataFrame]:
    """Pull the four trade tables and the HS6 label map into long-format DataFrames."""
    from loadFiles.models import (
        CountryExportToPartner, CountryExportToWorld,
        PartnerImportFromWorld, WorldExport, HSProduct,
    )

    bilateral_records = list(
        CountryExportToPartner.objects.values(
            'reporter', 'partner', 'product_code', 'year', 'value_usd_thousands')
    )
    reporter_world_records = list(
        CountryExportToWorld.objects.values(
            'reporter', 'product_code', 'year', 'value_usd_thousands')
    )
    partner_import_records = list(
        PartnerImportFromWorld.objects.values(
            'partner', 'product_code', 'year', 'value_usd_thousands')
    )
    world_export_records = list(
        WorldExport.objects.values('product_code', 'year', 'value_usd_thousands')
    )
    hs_label_by_product_code = dict(
        HSProduct.objects.values_list('product_code', 'product_label')
    )

    bilateral_df = pd.DataFrame(bilateral_records).rename(columns=_RENAMES['bilateral'])
    reporter_world_df = pd.DataFrame(reporter_world_records).rename(columns=_RENAMES['reporter_world'])
    partner_import_df = pd.DataFrame(partner_import_records).rename(columns=_RENAMES['partner_import'])
    world_export_df = pd.DataFrame(world_export_records).rename(columns=_RENAMES['world_export'])
    world_export_df['Product label'] = (
        world_export_df['Product code'].map(hs_label_by_product_code).fillna('All products')
    )

    for df in (bilateral_df, reporter_world_df, partner_import_df, world_export_df):
        df['Year'] = df['Year'].astype(str)

    return {
        'bilateral': bilateral_df,
        'reporter_world': reporter_world_df,
        'partner_import': partner_import_df,
        'world_export': world_export_df,
    }


def _extract_totals(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Pull TOTAL rows out of each product-level table to act as per-year denominators."""
    reporter_world_df = frames['reporter_world']
    partner_import_df = frames['partner_import']
    world_export_df = frames['world_export']

    reporter_totals = (
        reporter_world_df[_is_total(reporter_world_df['Product code'])]
        [['Country', 'Year', 'Reporter Export To World']]
        .rename(columns={'Reporter Export To World': "Reporter's Total Export To World"})
    )
    partner_totals = (
        partner_import_df[_is_total(partner_import_df['Product code'])]
        [['partner', 'Year', 'Partner Import From World']]
        .rename(columns={'Partner Import From World': "Partner's Total Import From World"})
    )
    world_totals = (
        world_export_df[_is_total(world_export_df['Product code'])]
        [['Year', 'World Export of item k']]
        .rename(columns={'World Export of item k': 'Total World Export'})
    )
    return {
        'reporter_totals': reporter_totals,
        'partner_totals': partner_totals,
        'world_totals': world_totals,
    }


def _drop_total_rows(frames: dict[str, pd.DataFrame]) -> None:
    """In-place drop of TOTAL rows from each product-level table."""
    for key in ('bilateral', 'reporter_world', 'partner_import', 'world_export'):
        df = frames[key]
        frames[key] = df[~_is_total(df['Product code'])]


# HS codes that were vacated and later re-used for a different product, so their
# pre-reintroduction years carry meaningless trade (near-zero world denominator,
# two products in one series). Keyed by HS-code prefix → first valid year.
# Dropped from EVERY product-level frame here in the loader, so the numerator
# (HS6 Cij sum) and ALL denominators (world/partner/reporter HS4/HS2/SITC totals)
# are built from the same code universe — see the chapter-85 denominator note.
#   8524: vacated in HS2007 ("recorded media"); reintroduced in HS2022
#         ("flat-panel display modules"). Valid only 2022+.
RESTRICTED_CODE_FIRST_VALID_YEAR = {'8524': 2022}


def _drop_restricted_codes(frames: dict[str, pd.DataFrame]) -> None:
    """In-place drop of vacated/re-used codes in years before their current
    meaning, from every product-level table (numerator and denominators alike)."""
    for key in ('bilateral', 'reporter_world', 'partner_import', 'world_export'):
        df = frames[key]
        product_code = df['Product code'].astype(str)
        year = pd.to_numeric(df['Year'], errors='coerce')
        keep = pd.Series(True, index=df.index)
        for code_prefix, first_valid_year in RESTRICTED_CODE_FIRST_VALID_YEAR.items():
            contaminated = product_code.str[:len(code_prefix)].eq(code_prefix) & (year < first_valid_year)
            keep &= ~contaminated
        frames[key] = df[keep]


def _world_hs4_totals(world_export_df: pd.DataFrame) -> pd.DataFrame:
    """
    World total exports per HS4 heading per year, summed across ALL HS6 codes in
    each heading. Reporter-independent denominator for the HS4 aggregation step.
    """
    return (
        world_export_df.assign(HS4=world_export_df['Product code'].astype(str).str[:4])
        .groupby(['HS4', 'Year'], as_index=False)['World Export of item k']
        .sum()
        .rename(columns={'World Export of item k': 'World Export HS4 Total'})
    )


def _partner_hs4_totals(partner_import_df: pd.DataFrame) -> pd.DataFrame:
    """
    Partner imports per HS4 heading per year, summed directly from the canonical
    PartnerImportFromWorld DB rows. Reporter-independent — used as the
    M_partner_HS4 numerator for HS4 RCA Import, broadcast across reporters.
    """
    return (
        partner_import_df.assign(HS4=partner_import_df['Product code'].astype(str).str[:4])
        .groupby(['partner', 'HS4', 'Year'], as_index=False)['Partner Import From World']
        .sum()
        .rename(columns={'Partner Import From World': 'Partner Import HS4 Total'})
    )


def _reporter_hs4_totals(reporter_world_df: pd.DataFrame) -> pd.DataFrame:
    """
    Reporter exports per HS4 heading per year, summed directly from the canonical
    CountryExportToWorld DB rows. Partner-independent — used as the
    X_reporter_HS4 numerator for HS4 RCA Export.
    """
    return (
        reporter_world_df.assign(HS4=reporter_world_df['Product code'].astype(str).str[:4])
        .groupby(['Country', 'HS4', 'Year'], as_index=False)['Reporter Export To World']
        .sum()
        .rename(columns={'Reporter Export To World': 'Reporter Export HS4 Total'})
    )


def _world_hs2_totals(world_export_df: pd.DataFrame) -> pd.DataFrame:
    """World exports per HS2 chapter per year. Reporter-independent denominator."""
    return (
        world_export_df.assign(HS2=world_export_df['Product code'].astype(str).str[:2])
        .groupby(['HS2', 'Year'], as_index=False)['World Export of item k']
        .sum()
        .rename(columns={'World Export of item k': 'World Export HS2 Total'})
    )


def _partner_hs2_totals(partner_import_df: pd.DataFrame) -> pd.DataFrame:
    """Partner imports per HS2 chapter per year, from canonical PartnerImportFromWorld."""
    return (
        partner_import_df.assign(HS2=partner_import_df['Product code'].astype(str).str[:2])
        .groupby(['partner', 'HS2', 'Year'], as_index=False)['Partner Import From World']
        .sum()
        .rename(columns={'Partner Import From World': 'Partner Import HS2 Total'})
    )


def _reporter_hs2_totals(reporter_world_df: pd.DataFrame) -> pd.DataFrame:
    """Reporter exports per HS2 chapter per year, from canonical CountryExportToWorld."""
    return (
        reporter_world_df.assign(HS2=reporter_world_df['Product code'].astype(str).str[:2])
        .groupby(['Country', 'HS2', 'Year'], as_index=False)['Reporter Export To World']
        .sum()
        .rename(columns={'Reporter Export To World': 'Reporter Export HS2 Total'})
    )


def hs_revision_for_year(year) -> str:
    """HS revision in force during a given calendar year. HS editions take
    effect in January of their year, so the boundaries are calendar-clean.

    2002–06 → '2002', 2007–11 → '2007', 2012–16 → '2012', 2017–21 → '2017',
    2022+ → '2022'. (2001 maps to '2002'; no HS1996 concordance is loaded, so
    those rows simply stay unmapped — the main pipeline does not use SITC.)"""
    year = int(year)
    if year <= 2006:
        return '2002'
    if year <= 2011:
        return '2007'
    if year <= 2016:
        return '2012'
    if year <= 2021:
        return '2017'
    return '2022'


def _hs6_to_sitc_concordance() -> pd.DataFrame:
    """Vintage-aware HS6 → SITC section table from HSSITCConcordance, as a
    DataFrame [product_code, hs_revision, sitc_section]. Empty if not loaded."""
    from loadFiles.models import HSSITCConcordance
    return pd.DataFrame(
        HSSITCConcordance.objects.values_list('product_code', 'hs_revision', 'sitc_section'),
        columns=['product_code', 'hs_revision', 'sitc_section'],
    )


def _assign_sitc_section(trade_df: pd.DataFrame, concordance: pd.DataFrame) -> pd.DataFrame:
    """Add a 'SITC' (section) column to a trade frame by mapping each HS6 row
    through the concordance for the HS revision active in that row's year.
    Rows whose (HS6, revision) pair is absent from the concordance are dropped."""
    revision = trade_df['Year'].map(hs_revision_for_year)
    annotated = trade_df.assign(
        _Revision=revision.values,
        _HS6=trade_df['Product code'].astype(str),
    )
    merged = annotated.merge(
        concordance,
        left_on=['_HS6', '_Revision'],
        right_on=['product_code', 'hs_revision'],
        how='left',
    )
    merged = merged.dropna(subset=['sitc_section'])
    return merged.rename(columns={'sitc_section': 'SITC'}).drop(
        columns=['_Revision', '_HS6', 'product_code', 'hs_revision']
    )


def _world_sitc_totals(world_export_df: pd.DataFrame, concordance: pd.DataFrame) -> pd.DataFrame:
    """World exports per SITC section per year. Empty if no concordance."""
    if concordance.empty:
        return pd.DataFrame(columns=['SITC', 'Year', 'World Export SITC Total'])
    df = _assign_sitc_section(world_export_df, concordance)
    return (
        df.groupby(['SITC', 'Year'], as_index=False)['World Export of item k']
        .sum()
        .rename(columns={'World Export of item k': 'World Export SITC Total'})
    )


def _partner_sitc_totals(partner_import_df: pd.DataFrame, concordance: pd.DataFrame) -> pd.DataFrame:
    """Partner imports per SITC section per year. Empty if no concordance."""
    if concordance.empty:
        return pd.DataFrame(columns=['partner', 'SITC', 'Year', 'Partner Import SITC Total'])
    df = _assign_sitc_section(partner_import_df, concordance)
    return (
        df.groupby(['partner', 'SITC', 'Year'], as_index=False)['Partner Import From World']
        .sum()
        .rename(columns={'Partner Import From World': 'Partner Import SITC Total'})
    )


def _reporter_sitc_totals(reporter_world_df: pd.DataFrame, concordance: pd.DataFrame) -> pd.DataFrame:
    """Reporter exports per SITC section per year. Empty if no concordance."""
    if concordance.empty:
        return pd.DataFrame(columns=['Country', 'SITC', 'Year', 'Reporter Export SITC Total'])
    df = _assign_sitc_section(reporter_world_df, concordance)
    return (
        df.groupby(['Country', 'SITC', 'Year'], as_index=False)['Reporter Export To World']
        .sum()
        .rename(columns={'Reporter Export To World': 'Reporter Export SITC Total'})
    )


def _merge_for_partner(
    partner_name: str,
    frames: dict[str, pd.DataFrame],
    totals: dict[str, pd.DataFrame],
    world_hs4_totals_df: pd.DataFrame,
    world_export_product_labels: pd.DataFrame,
) -> pd.DataFrame | None:
    bilateral_df = frames['bilateral']
    reporter_world_df = frames['reporter_world']
    partner_import_df = frames['partner_import']
    world_export_df = frames['world_export']

    reporters_for_partner = bilateral_df.loc[
        bilateral_df['partner'] == partner_name, 'Country'
    ].unique()
    if len(reporters_for_partner) == 0:
        return None

    reporter_world_for_partner = reporter_world_df[
        reporter_world_df['Country'].isin(reporters_for_partner)
    ].copy()
    bilateral_for_partner = (
        bilateral_df[bilateral_df['partner'] == partner_name].drop(columns=['partner'])
    )
    partner_imports_for_partner = (
        partner_import_df[partner_import_df['partner'] == partner_name].drop(columns=['partner'])
    )
    partner_total_for_partner = (
        totals['partner_totals'][totals['partner_totals']['partner'] == partner_name]
        .drop(columns=['partner'])
    )

    merged = (
        reporter_world_for_partner
        .merge(bilateral_for_partner,            on=['Country', 'Year', 'Product code'], how='left')
        .merge(partner_imports_for_partner,      on=['Year', 'Product code'],            how='left')
        .merge(world_export_df[['Year', 'Product code', 'World Export of item k']],
                                                 on=['Year', 'Product code'],            how='left')
        .merge(world_export_product_labels,      on='Product code',                      how='left')
        .merge(totals['reporter_totals'],        on=['Country', 'Year'],                 how='left')
        .merge(partner_total_for_partner,        on=['Year'],                            how='left')
        .merge(totals['world_totals'],           on=['Year'],                            how='left')
    )

    merged['HS4'] = merged['Product code'].astype(str).str[:4]
    merged = merged.merge(world_hs4_totals_df, on=['HS4', 'Year'], how='left')
    merged = merged.drop(columns=['HS4'])

    merged[['Reporter Export To Partner', 'Partner Import From World']] = (
        merged[['Reporter Export To Partner', 'Partner Import From World']].fillna(0)
    )

    merged = merged[_FINAL_COLUMNS]
    merged.sort_values(
        by=['Product code', 'Year'], ascending=[True, False],
        inplace=True, ignore_index=True,
    )
    return merged


def load_all(
    partner_names: tuple[str, ...] = ('China', 'US'),
    logger: logging.Logger | None = None,
) -> LoadedTradeData | None:
    """
    Build the per-partner long-format trade DataFrame plus the precomputed
    HS4 totals and denominator lookups from the database.

    Returns None if no WorldExport rows are loaded.
    """
    log = logger or logging.getLogger(__name__)

    frames = _query_long_format()
    if frames['world_export'].empty:
        log.error("No WorldExport data in DB. Run TradeMapLoader first.")
        return None

    totals = _extract_totals(frames)
    _drop_total_rows(frames)
    _drop_restricted_codes(frames)

    world_export_product_labels = (
        frames['world_export'][['Product code', 'Product label']].drop_duplicates('Product code')
    )
    world_hs4_totals_df    = _world_hs4_totals(frames['world_export'])
    partner_hs4_totals_df  = _partner_hs4_totals(frames['partner_import'])
    reporter_hs4_totals_df = _reporter_hs4_totals(frames['reporter_world'])
    world_hs2_totals_df    = _world_hs2_totals(frames['world_export'])
    partner_hs2_totals_df  = _partner_hs2_totals(frames['partner_import'])
    reporter_hs2_totals_df = _reporter_hs2_totals(frames['reporter_world'])
    sitc_concordance       = _hs6_to_sitc_concordance()
    world_sitc_totals_df    = _world_sitc_totals(frames['world_export'], sitc_concordance)
    partner_sitc_totals_df  = _partner_sitc_totals(frames['partner_import'], sitc_concordance)
    reporter_sitc_totals_df = _reporter_sitc_totals(frames['reporter_world'], sitc_concordance)

    hs6_per_partner: dict[str, pd.DataFrame] = {}
    for partner_name in partner_names:
        merged = _merge_for_partner(
            partner_name, frames, totals, world_hs4_totals_df, world_export_product_labels,
        )
        if merged is None:
            log.warning("No bilateral data for partner %s in DB.", partner_name)
            continue
        hs6_per_partner[partner_name] = merged
        log.info("Loaded and merged %d rows for partner %s.", len(merged), partner_name)

    return LoadedTradeData(
        hs6_per_partner     = hs6_per_partner,
        world_hs4_totals    = world_hs4_totals_df,
        partner_hs4_totals  = partner_hs4_totals_df,
        reporter_hs4_totals = reporter_hs4_totals_df,
        world_hs2_totals    = world_hs2_totals_df,
        partner_hs2_totals  = partner_hs2_totals_df,
        reporter_hs2_totals = reporter_hs2_totals_df,
        world_sitc_totals    = world_sitc_totals_df,
        partner_sitc_totals  = partner_sitc_totals_df,
        reporter_sitc_totals = reporter_sitc_totals_df,
        reporter_totals     = totals['reporter_totals'],
        partner_totals      = totals['partner_totals'],
        world_totals        = totals['world_totals'],
    )

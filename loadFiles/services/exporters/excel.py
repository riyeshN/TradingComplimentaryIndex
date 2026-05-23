"""
Excel workbook exporter — writes {partner}_TCI.xlsx.

Sheets present depend on the scope:
  ICT scope        — Country Summary, HS4 Summary, HS6 Detail
  Strategic scope  — Country Summary, HS2 Summary, HS4 Summary, HS6 Detail
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ._filter import filter_scope

# Cij column conventions across all summary sheets:
#   TCI_Drysdale_Garnaut — weighted (Σ HS6 DG). Methodological primary.
#   TCI_RCA_Product      — unweighted tier-level RCA_x × RCA_m. Matches the
#                          per-product index published by Yang (2023).
COUNTRY_SUMMARY_COLUMNS = {
    'Country':                  'Country',
    'Year':                     'Year',
    'Headline_Cij_DG':          'Headline_Cij_Drysdale_Garnaut',
    'Headline_Cij_RCA_Product': 'Headline_Cij_RCA_Product',
    'Num_Active_HS6_Pairs':     'Active_HS6_Pairs',
}

HS4_SUMMARY_COLUMNS = {
    'Country':                'Country',
    'Year':                   'Year',
    'HS4':                    'HS4',
    'TCI_DG_4digit':          'TCI_Drysdale_Garnaut',
    'TCI_RCA_Product_4digit': 'TCI_RCA_Product',
    'RCA_Export_4digit':      'RCA_Reporter_Export',
    'RCA_Import_4digit':      'RCA_Partner_Import',
    'Total_Reporter_Export':  'Total_Reporter_Export_USD_thousands',
    'Total_Partner_Import':   'Total_Partner_Import_USD_thousands',
    'Total_World_Export_K':   'Total_World_Export_HS4_USD_thousands',
    'Num_Active_HS6_Pairs':   'Active_HS6_Pairs',
}

HS2_SUMMARY_COLUMNS = {
    'Country':                'Country',
    'Year':                   'Year',
    'HS2':                    'HS2',
    'TCI_DG_2digit':          'TCI_Drysdale_Garnaut',
    'TCI_RCA_Product_2digit': 'TCI_RCA_Product',
    'RCA_Export_2digit':      'RCA_Reporter_Export',
    'RCA_Import_2digit':      'RCA_Partner_Import',
    'Total_Reporter_Export':  'Total_Reporter_Export_USD_thousands',
    'Total_Partner_Import':   'Total_Partner_Import_USD_thousands',
    'Total_World_Export_K':   'Total_World_Export_HS2_USD_thousands',
    'Num_Active_HS6_Pairs':   'Active_HS6_Pairs',
}

SITC_SUMMARY_COLUMNS = {
    'Country':                'Country',
    'Year':                   'Year',
    'SITC':                   'SITC_Section',
    'TCI_DG_sitc':            'TCI_Drysdale_Garnaut',
    'TCI_RCA_Product_sitc':   'TCI_RCA_Product',
    'RCA_Export_sitc':        'RCA_Reporter_Export',
    'RCA_Import_sitc':        'RCA_Partner_Import',
    'Num_Active_HS6_Pairs':   'Active_HS6_Pairs',
}

HS6_DETAIL_COLUMNS = {
    'Country':                          'Country',
    'Year':                             'Year',
    'HS4':                              'HS4',
    'Product code':                     'Product_Code',
    'Product label':                    'Product_Label',
    'Reporter Export To Partner':       'Reporter_Export_To_Partner_USD_thousands',
    'Reporter Export To World':         'Reporter_Export_To_World_USD_thousands',
    'Partner Import From World':        'Partner_Import_From_World_USD_thousands',
    'World Export of item k':           'World_Export_HS6_USD_thousands',
    'World Export HS4 Total':           'World_Export_HS4_Total_USD_thousands',
    "Reporter's Total Export To World": 'Total_Reporter_Export_USD_thousands',
    "Partner's Total Import From World":'Total_Partner_Import_USD_thousands',
    'Total World Export':               'Total_World_Export_USD_thousands',
    'TCI_Drysdale_Garnaut':             'TCI_Drysdale_Garnaut',
    'TCI_RCA_DG_Decomposition':         'TCI_RCA_DG_Decomposition',
    'RCA Reporter Export':              'RCA_Reporter_Export',
    'RCA Partner Import':               'RCA_Partner_Import',
    'Proportion World Trade':           'Proportion_World_Trade',
    'Active_Pair':                      'Active_Pair',
}


def export_excel(
    hs4_index_by_partner: dict[str, pd.DataFrame],
    hs6_with_indicators_by_partner: dict[str, pd.DataFrame],
    headline_cij_by_partner: dict[str, pd.DataFrame],
    export_dir: Path,
    hs2_index_by_partner: dict[str, pd.DataFrame] | None = None,
    sitc_index_by_partner: dict[str, pd.DataFrame] | None = None,
    countries: list[str] | None = None,
    hs4_codes: list[str] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Write one Excel workbook per partner. Adds an HS2 Summary sheet if
    `hs2_index_by_partner` is supplied (strategic scope), or an SITC Summary
    sheet if `sitc_index_by_partner` is supplied (Yang scope)."""
    log = logger or logging.getLogger(__name__)
    export_dir.mkdir(parents=True, exist_ok=True)

    for partner_name in hs4_index_by_partner:
        hs4_data = filter_scope(
            hs4_index_by_partner[partner_name].copy(), countries, hs4_codes,
        )
        hs6_data = filter_scope(
            hs6_with_indicators_by_partner[partner_name].copy(), countries, hs4_codes,
        )
        # hs4_codes filter applies only to HS4/HS6/HS2 sheets — Country Summary
        # always reports the full scope headline regardless of subset.
        country_data = filter_scope(
            headline_cij_by_partner[partner_name].copy(), countries, None,
        )

        country_sheet = (
            country_data[list(COUNTRY_SUMMARY_COLUMNS.keys())]
            .rename(columns=COUNTRY_SUMMARY_COLUMNS)
            .sort_values(['Country', 'Year'])
            .reset_index(drop=True)
        )
        hs4_sheet = (
            hs4_data[list(HS4_SUMMARY_COLUMNS.keys())]
            .rename(columns=HS4_SUMMARY_COLUMNS)
            .sort_values(['Country', 'Year', 'HS4'])
            .reset_index(drop=True)
        )
        hs6_sheet = (
            hs6_data[list(HS6_DETAIL_COLUMNS.keys())]
            .rename(columns=HS6_DETAIL_COLUMNS)
            .sort_values(['Country', 'Year', 'HS4', 'Product_Code'])
            .reset_index(drop=True)
        )

        hs2_sheet = None
        if hs2_index_by_partner is not None and partner_name in hs2_index_by_partner:
            hs2_data = hs2_index_by_partner[partner_name].copy()
            if countries is not None:
                hs2_data = hs2_data[hs2_data['Country'].isin(countries)]
            hs2_sheet = (
                hs2_data[list(HS2_SUMMARY_COLUMNS.keys())]
                .rename(columns=HS2_SUMMARY_COLUMNS)
                .sort_values(['Country', 'Year', 'HS2'])
                .reset_index(drop=True)
            )

        sitc_sheet = None
        if sitc_index_by_partner is not None and partner_name in sitc_index_by_partner:
            sitc_data = sitc_index_by_partner[partner_name].copy()
            if countries is not None:
                sitc_data = sitc_data[sitc_data['Country'].isin(countries)]
            sitc_sheet = (
                sitc_data[list(SITC_SUMMARY_COLUMNS.keys())]
                .rename(columns=SITC_SUMMARY_COLUMNS)
                .sort_values(['Country', 'Year', 'SITC_Section'])
                .reset_index(drop=True)
            )

        output_path = export_dir / f"{partner_name}_TCI.xlsx"
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            country_sheet.to_excel(writer, sheet_name='Country Summary', index=False)
            if sitc_sheet is not None:
                sitc_sheet.to_excel(writer, sheet_name='SITC Summary', index=False)
            if hs2_sheet is not None:
                hs2_sheet.to_excel(writer, sheet_name='HS2 Summary', index=False)
            hs4_sheet.to_excel(writer, sheet_name='HS4 Summary', index=False)
            hs6_sheet.to_excel(writer, sheet_name='HS6 Detail', index=False)

        sheet_summary = (
            f"{len(country_sheet)} country-year, "
            + (f"{len(sitc_sheet)} SITC, " if sitc_sheet is not None else "")
            + (f"{len(hs2_sheet)} HS2, " if hs2_sheet is not None else "")
            + f"{len(hs4_sheet)} HS4, {len(hs6_sheet)} HS6"
        )
        log.info("Exported %s (%s).", output_path, sheet_summary)

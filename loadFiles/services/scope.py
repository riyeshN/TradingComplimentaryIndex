"""
Analysis-scope definitions for the TCI pipeline.

Two scopes are supported:

  SCOPE_ICT       — UNCTAD ICT goods classification (HS 2022), 23 HS4 headings.
                    Part II of the paper.

  SCOPE_STRATEGIC — Strategic industries per Freund, Mattoo, Mulabdic and Ruta
                    (2024), "Is U.S. Trade Policy Reshaping Global Supply
                    Chains?", JIE 152, Appendix Table 1. Eleven HS2 chapters.
                    Part I of the paper.

The `Scope` record carries everything scope-specific so the pipeline math
stays parameterised. See `docs/methodology_for_economists.md` for the
research context and `readings/` for source documents.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    """Describes one analysis scope used by the TCI pipeline."""

    # Short identifier used for output subdirectory naming (e.g. 'ict', 'strategic').
    name: str

    # Length in characters of the HS prefix to compare against `filter_codes`.
    # 4 → match HS4 headings (e.g. '8542'). 2 → match HS2 chapters (e.g. '84').
    filter_digits: int

    # HS prefixes that define which HS6 codes are kept after filtering.
    filter_codes: tuple[str, ...]

    # Primary reporting tier — drives chart granularity, Word doc table grouping,
    # and which Excel summary sheets are emitted. 'HS4' for ICT, 'HS2' for strategic.
    primary_tier: str

    # Display labels keyed by the primary-tier code. Used in Word docs and
    # chart titles. Sourced from the same authority as filter_codes.
    primary_labels: dict[str, str]


SCOPE_ICT = Scope(
    name='ict',
    filter_digits=4,
    filter_codes=(
        '8443', '8470', '8471', '8472', '8473',
        '8517', '8518', '8519', '8521', '8522', '8523', '8524', '8525',
        '8527', '8528', '8529', '8531', '8534', '8540', '8541', '8542',
        '9013', '9504',
    ),
    primary_tier='HS4',
    primary_labels={
        '8443': 'Printing machinery',
        '8470': 'Calculating machines, data recording',
        '8471': 'Automatic data-processing machines',
        '8472': 'Office machines',
        '8473': 'Parts and accessories',
        '8517': 'Telephone sets, smartphones, network apparatus',
        '8518': 'Microphones, loudspeakers',
        '8519': 'Sound recording / reproducing apparatus',
        '8521': 'Video recording / reproducing apparatus',
        '8522': 'Parts for sound and video apparatus',
        '8523': 'Discs, tapes, solid-state storage, smart cards',
        '8524': 'Flat panel display modules',
        '8525': 'Transmission apparatus for radio / TV',
        '8527': 'Reception apparatus for radio-broadcasting',
        '8528': 'Monitors, projectors',
        '8529': 'Parts for displays and transmission apparatus',
        '8531': 'Electric signalling apparatus',
        '8534': 'Printed circuits',
        '8540': 'Thermionic, cathode and photo-cathode tubes',
        '8541': 'Semiconductor devices, photosensitive elements',
        '8542': 'Electronic integrated circuits',
        '9013': 'Lasers, optical appliances',
        '9504': 'Video game consoles',
    },
)


SCOPE_STRATEGIC = Scope(
    name='strategic',
    filter_digits=2,
    # JIE Appendix Table 1 lists eleven HS2 chapters; chapter 98 ("Special
    # classification provisions") is omitted here because TradeMap source data
    # contains zero rows for that chapter — it's country-specific reserved
    # codes (US 9801/9802 etc.) typically suppressed from international trade
    # datasets.
    filter_codes=('28', '29', '30', '38', '84', '85', '87', '88', '90', '93'),
    primary_tier='HS2',
    primary_labels={
        '28': 'Inorganic chemicals, precious metals, rare earth, radioactive',
        '29': 'Organic chemicals',
        '30': 'Pharmaceutical products',
        '38': 'Chemical products n.e.c',
        '84': 'Nuclear reactors, boilers, machinery',
        '85': 'Electrical machinery, sound/TV equipment',
        '87': 'Vehicles (non-rail) and parts',
        '88': 'Aircraft, spacecraft and parts',
        '90': 'Optical, measuring, medical instruments',
        '93': 'Arms and ammunition',
    },
)


SCOPE_YANG = Scope(
    name='yang',
    filter_digits=2,
    # Empty filter_codes = keep the entire HS6 universe (no HS-prefix filter).
    # Yang (2023) spans all SITC sections, so no commodity scope restriction;
    # the SITC grouping happens in the SITC aggregation tier.
    filter_codes=(),
    primary_tier='SITC',
    primary_labels={
        '0': 'Food and live animals',
        '1': 'Beverages and tobacco',
        '2': 'Crude materials, inedible, except fuels',
        '3': 'Mineral fuels, lubricants',
        '4': 'Animal and vegetable oils, fats, waxes',
        '5': 'Chemicals and related products',
        '6': 'Manufactured goods classified by material',
        '7': 'Machinery and transport equipment',
        '8': 'Miscellaneous manufactured articles',
        '9': 'Commodities not classified elsewhere',
    },
)


SCOPES_BY_NAME = {
    SCOPE_ICT.name: SCOPE_ICT,
    SCOPE_STRATEGIC.name: SCOPE_STRATEGIC,
    SCOPE_YANG.name: SCOPE_YANG,
}

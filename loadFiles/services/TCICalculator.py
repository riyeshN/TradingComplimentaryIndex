import logging
from pathlib import Path

import pandas as pd

from loadFiles.services import sql_tci
from loadFiles.services.scope import Scope, SCOPE_ICT
from loadFiles.services.exporters import (
    export_excel, export_hs4_tci_charts, export_word_summary,
)

EXPORT_DIR = "./data/TradeMapData/export/"
# The HS6 indicators, tier aggregations, headline and SITC frames are all
# produced by SQL queries in loadFiles.services.sql_tci. Year window (2001–2024),
# scope (HS-prefix) filtering and the restricted-code drop (8524 before 2022) all
# live in those queries, so the numerator and every tier denominator share one
# code universe.


class TCICalculator:
    """
    Calculates Trade Complementarity Index (TCI) over the UNCTAD ICT goods scope
    (HS 2022, 23 HS4 headings, 107 HS6 codes) for Indo-Pacific reporters versus
    China and the United States.

    Three-tier output, all derived from a single HS6 source:
      - HS6 Cij (Drysdale-Garnaut)         — single-product values, audit trail.
      - HS4 Cij  = sum of HS6 Cij in heading — preserves bilateral product matching.
      - Headline = sum of HS6 Cij over scope — single Cij per (reporter, partner, year).

    Two TCI forms are reported at every tier:
      - Drysdale-Garnaut (weighted): (Xi_k/Xi) × (Mj_k/Mj) × (WX/WX_k)   — primary.
      - RCA product (unweighted):    RCA_export × RCA_import             — secondary.

    HS4 RCA is reported as an auxiliary heading-level specialisation metric. It is
    derived as a weighted average of HS6 RCA values with weight = (W_k / W_HS4),
    and is not used in the HS4 Cij calculation.

    Data is read from the database (loaded by TradeMapLoader).
    Results are exported as a three-sheet Excel workbook per partner to EXPORT_DIR.
    See README.md and docs/validation_methodology.md for the full methodology.
    """

    def __init__(self, scope: Scope = SCOPE_ICT,
                 partner_names: tuple[str, ...] = ('China', 'US')):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.scope = scope
        self.partner_names = partner_names

        # Built during processing — keyed by partner ("China"/"US", or "CCE" for Yang).
        # Each frame is produced by a SQL query in loadFiles.services.sql_tci; the
        # column contract matches what the exporters/tests consume.
        self.hs6_trade_data_by_partner:      dict[str, pd.DataFrame] = {}
        self.hs4_index_by_partner:           dict[str, pd.DataFrame] = {}
        self.hs2_index_by_partner:           dict[str, pd.DataFrame] = {}
        self.sitc_index_by_partner:          dict[str, pd.DataFrame] = {}
        self.hs6_with_indicators_by_partner: dict[str, pd.DataFrame] = {}
        self.headline_cij_by_partner:        dict[str, pd.DataFrame] = {}

    # ── Public entry points ──────────────────────────────────────────────────

    def run_indicators(self):
        """Load + compute every Cij/RCA tier, no file export. Shared by run()
        and by validation commands so they read identical pipeline output."""
        self._load_from_db()
        self._filter_by_scope_and_year()
        self._calculate_tci_drysdale_garnaut()
        self._calculate_rca_and_tci_rca()
        self._aggregate_hs6_to_hs4()
        if self.scope.primary_tier == 'HS2':
            self._aggregate_hs4_to_hs2()
        if self.scope.primary_tier == 'SITC':
            self._aggregate_to_sitc()
        self._calculate_headline_cij()
        self._verify_partner_invariants()

    def run(self, countries: list[str] | None = None, hs4_codes: list[str] | None = None):
        self.run_indicators()
        self._export_excel(countries, hs4_codes)
        self._export_hs4_tci_charts(countries, hs4_codes)
        self._export_word_summary(countries, hs4_codes)

    # ── Load from DB ─────────────────────────────────────────────────────────

    def _load_from_db(self):
        """Build the per-partner HS6 frame — base trade values *and* every HS6
        indicator — via one SQL query per partner (sql_tci.load_hs6_indicators).
        The query already applies the scope (HS-prefix) and year filters and
        drops restricted codes, so the result is the scoped, indicator-complete
        HS6 frame. Replaces the old trade_data_loader merge + the row-wise
        DG/RCA pandas math."""
        for partner_name in self.partner_names:
            frame = sql_tci.load_hs6_indicators(self.scope, partner_name)
            if frame.empty:
                self.logger.warning("No HS6 rows for partner %s.", partner_name)
                continue
            self.hs6_trade_data_by_partner[partner_name] = frame
            self.logger.info("Loaded %d HS6 indicator rows for partner %s.",
                             len(frame), partner_name)

    # ── Pipeline steps ───────────────────────────────────────────────────────
    # Scope/year filtering and the HS6 DG/RCA math now live in the SQL load step
    # (sql_tci). These staged methods are retained as no-ops so the staged entry
    # points used by RCAFormulaValidationTest / validate_rca_against_wits
    # (load → filter → calculate → read RCA) keep working unchanged.

    def _filter_by_scope_and_year(self):
        """No-op: scope (HS-prefix) and year filtering are applied in the SQL
        load query (sql_tci.hs6_indicators_sql)."""

    def _calculate_tci_drysdale_garnaut(self):
        """No-op: TCI_Drysdale_Garnaut is computed in the SQL load query."""

    def _calculate_rca_and_tci_rca(self):
        """No-op: HS6 RCAs, Proportion World Trade, TCI_RCA_DG_Decomposition and
        Active_Pair are computed in the SQL load query."""

    def _aggregate_hs6_to_hs4(self):
        """
        HS4 Cij = sum of HS6 Cij within each heading (scoped numerator), with
        HS4 RCAs computed from canonical-source HS4 totals. Computed by
        sql_tci.tier_index_sql(digits=4). Also populates
        hs6_with_indicators_by_partner = the loaded HS6 frame + an 'HS4' column
        (the audit trail the Excel HS6 sheet and rca_only exporter read).
        """
        for partner_name, hs6_data in self.hs6_trade_data_by_partner.items():
            self.hs4_index_by_partner[partner_name] = sql_tci.load_tier_index(
                self.scope, partner_name, digits=4, suffix='4digit')
            with_hs4 = hs6_data.copy()
            with_hs4['HS4'] = with_hs4['Product code'].astype(str).str[:4]
            self.hs6_with_indicators_by_partner[partner_name] = with_hs4

    def _aggregate_hs4_to_hs2(self):
        """HS2 Cij = sum of HS6 Cij within each chapter; HS2 RCAs from canonical
        HS2 totals. Computed by sql_tci.tier_index_sql(digits=2)."""
        for partner_name in self.hs6_with_indicators_by_partner:
            self.hs2_index_by_partner[partner_name] = sql_tci.load_tier_index(
                self.scope, partner_name, digits=2, suffix='2digit')

    def _aggregate_to_sitc(self):
        """SITC-section aggregation for the Yang (2023) comparison (vintage-aware
        HS6→SITC). Computed by sql_tci.sitc_index_sql. If the concordance table
        is empty, sql_tci returns an empty frame and the partner is skipped —
        matching the old early-return behaviour."""
        for partner_name in self.hs6_with_indicators_by_partner:
            frame = sql_tci.load_sitc_index(self.scope, partner_name)
            if frame.empty:
                self.logger.warning(
                    "SITC aggregation skipped for %s: HSSITCConcordance is empty.",
                    partner_name)
                continue
            self.sitc_index_by_partner[partner_name] = frame

    def _calculate_headline_cij(self):
        """Headline Cij per (reporter, year) over the full scope.
        Computed by sql_tci.headline_sql."""
        for partner_name in self.hs6_trade_data_by_partner:
            self.headline_cij_by_partner[partner_name] = sql_tci.load_headline(
                self.scope, partner_name)

    def _verify_partner_invariants(self, tolerance: float = 1e-9):
        """
        Pipeline-time regression guard. Raises ValueError when any of the four
        partner-side / reporter-side invariants is violated. Each invariant
        must hold by definition of Balassa RCA; a violation indicates a code
        bug that would otherwise produce silently wrong RCA values in the
        exported files.
        """
        partner_frames_hs6 = list(self.hs6_with_indicators_by_partner.items())
        partner_frames_hs4 = list(self.hs4_index_by_partner.items())
        if len(partner_frames_hs6) < 2 or len(partner_frames_hs4) < 2:
            self.logger.info("Partner-invariant check skipped: need >= 2 partner frames.")
            return

        def _raise(name: str, offending: pd.DataFrame) -> None:
            preview = offending.head(10).to_string(index=False)
            raise ValueError(
                f"Partner invariant violation: {name}\n"
                f"First {min(10, len(offending))} of {len(offending)} offending rows:\n"
                f"{preview}"
            )

        # 1. HS6 RCA Reporter Export — identical across partner frames
        # 2. HS6 TCI_Drysdale_Garnaut == TCI_RCA_DG_Decomposition (single-frame check)
        partner_a, hs6_a = partner_frames_hs6[0]
        partner_b, hs6_b = partner_frames_hs6[1]
        key_hs6 = ['Country', 'Year', 'Product code']
        joined_hs6 = (
            hs6_a[key_hs6 + ['RCA Reporter Export', 'TCI_Drysdale_Garnaut', 'TCI_RCA_DG_Decomposition']]
            .merge(
                hs6_b[key_hs6 + ['RCA Reporter Export']],
                on=key_hs6, how='inner', suffixes=(f'_{partner_a}', f'_{partner_b}'),
            )
        )
        rca_export_gap = (
            joined_hs6[f'RCA Reporter Export_{partner_a}']
            - joined_hs6[f'RCA Reporter Export_{partner_b}']
        ).abs()
        bad = joined_hs6[rca_export_gap > tolerance]
        if not bad.empty:
            _raise(f"HS6 RCA Reporter Export differs between {partner_a} and {partner_b}", bad)

        dg_decomposition_gap = (
            joined_hs6['TCI_Drysdale_Garnaut'] - joined_hs6['TCI_RCA_DG_Decomposition']
        ).abs()
        bad = joined_hs6[dg_decomposition_gap > tolerance]
        if not bad.empty:
            _raise("HS6 TCI_Drysdale_Garnaut != TCI_RCA_DG_Decomposition", bad)

        # 3. HS4 RCA_Export_4digit — identical across partner frames
        partner_a, hs4_a = partner_frames_hs4[0]
        partner_b, hs4_b = partner_frames_hs4[1]
        key_hs4 = ['Country', 'Year', 'HS4']
        joined_hs4 = hs4_a[key_hs4 + ['RCA_Export_4digit']].merge(
            hs4_b[key_hs4 + ['RCA_Export_4digit']],
            on=key_hs4, how='inner', suffixes=(f'_{partner_a}', f'_{partner_b}'),
        )
        rca4_export_gap = (
            joined_hs4[f'RCA_Export_4digit_{partner_a}']
            - joined_hs4[f'RCA_Export_4digit_{partner_b}']
        ).abs()
        bad = joined_hs4[rca4_export_gap > tolerance]
        if not bad.empty:
            _raise(f"HS4 RCA_Export_4digit differs between {partner_a} and {partner_b}", bad)

        # 4. HS4 RCA_Import_4digit — identical across reporters within each partner frame
        for partner_name, hs4_data in partner_frames_hs4:
            distinct_per_group = (
                hs4_data.groupby(['Year', 'HS4'])['RCA_Import_4digit']
                .agg(lambda s: s.max() - s.min())
            )
            bad_groups = distinct_per_group[distinct_per_group > tolerance]
            if not bad_groups.empty:
                offending = hs4_data.merge(
                    bad_groups.rename('gap').reset_index(),
                    on=['Year', 'HS4'], how='inner',
                ).sort_values(['Year', 'HS4', 'Country'])
                _raise(
                    f"HS4 RCA_Import_4digit varies across reporters for partner {partner_name}",
                    offending,
                )

        # 5–8. HS2-tier invariants — only when strategic scope has been aggregated
        if self.scope.primary_tier == 'HS2' and len(self.hs2_index_by_partner) >= 2:
            partner_frames_hs2 = list(self.hs2_index_by_partner.items())
            partner_a, hs2_a = partner_frames_hs2[0]
            partner_b, hs2_b = partner_frames_hs2[1]
            key_hs2 = ['Country', 'Year', 'HS2']

            # 5. HS2 RCA_Export_2digit — identical across partner frames
            joined_hs2 = hs2_a[key_hs2 + ['RCA_Export_2digit']].merge(
                hs2_b[key_hs2 + ['RCA_Export_2digit']],
                on=key_hs2, how='inner', suffixes=(f'_{partner_a}', f'_{partner_b}'),
            )
            rca2_export_gap = (
                joined_hs2[f'RCA_Export_2digit_{partner_a}']
                - joined_hs2[f'RCA_Export_2digit_{partner_b}']
            ).abs()
            bad = joined_hs2[rca2_export_gap > tolerance]
            if not bad.empty:
                _raise(
                    f"HS2 RCA_Export_2digit differs between {partner_a} and {partner_b}", bad,
                )

            # 6. HS2 RCA_Import_2digit — identical across reporters within each partner frame
            for partner_name, hs2_data in partner_frames_hs2:
                spread = (
                    hs2_data.groupby(['Year', 'HS2'])['RCA_Import_2digit']
                    .agg(lambda s: s.max() - s.min())
                )
                bad_groups = spread[spread > tolerance]
                if not bad_groups.empty:
                    offending = hs2_data.merge(
                        bad_groups.rename('gap').reset_index(),
                        on=['Year', 'HS2'], how='inner',
                    ).sort_values(['Year', 'HS2', 'Country'])
                    _raise(
                        f"HS2 RCA_Import_2digit varies across reporters for partner {partner_name}",
                        offending,
                    )

            # 7. Tier additivity: HS2 Cij DG == sum of HS4 Cij DG within HS2 chapter
            for partner_name, hs2_data in partner_frames_hs2:
                hs4_data = self.hs4_index_by_partner[partner_name].copy()
                hs4_data['HS2'] = hs4_data['HS4'].astype(str).str[:2]
                hs4_summed = (
                    hs4_data.groupby(['Country', 'Year', 'HS2'])['TCI_DG_4digit']
                    .sum().rename('HS4_Sum').reset_index()
                )
                joined = hs2_data[['Country', 'Year', 'HS2', 'TCI_DG_2digit']].merge(
                    hs4_summed, on=['Country', 'Year', 'HS2'], how='inner',
                )
                gap = (joined['TCI_DG_2digit'] - joined['HS4_Sum']).abs()
                bad = joined[gap > tolerance]
                if not bad.empty:
                    _raise(
                        f"HS2 Cij DG != sum of HS4 Cij within chapter for partner {partner_name}",
                        bad,
                    )

            # 8. Tier additivity: Headline Cij DG == sum of HS2 Cij DG (per Country, Year)
            for partner_name, hs2_data in partner_frames_hs2:
                headline = self.headline_cij_by_partner[partner_name]
                hs2_sum = (
                    hs2_data.groupby(['Country', 'Year'])['TCI_DG_2digit']
                    .sum().rename('HS2_Sum').reset_index()
                )
                joined = headline[['Country', 'Year', 'Headline_Cij_DG']].merge(
                    hs2_sum, on=['Country', 'Year'], how='inner',
                )
                gap = (joined['Headline_Cij_DG'] - joined['HS2_Sum']).abs()
                bad = joined[gap > tolerance]
                if not bad.empty:
                    _raise(
                        f"Headline Cij DG != sum of HS2 Cij for partner {partner_name}",
                        bad,
                    )

        check_count = 8 if self.scope.primary_tier == 'HS2' else 4
        self.logger.info(
            "Partner invariants verified: all %d checks pass.", check_count,
        )

    # ── Export ───────────────────────────────────────────────────────────────

    def _scope_export_dir(self) -> Path:
        return Path(EXPORT_DIR) / self.scope.name

    def _primary_tier_index_by_partner(self) -> dict[str, pd.DataFrame]:
        if self.scope.primary_tier == 'HS2':
            return self.hs2_index_by_partner
        if self.scope.primary_tier == 'SITC':
            return self.sitc_index_by_partner
        return self.hs4_index_by_partner

    def _export_excel(self, countries: list[str] | None, hs4_codes: list[str] | None):
        export_excel(
            self.hs4_index_by_partner,
            self.hs6_with_indicators_by_partner,
            self.headline_cij_by_partner,
            self._scope_export_dir(),
            hs2_index_by_partner=(
                self.hs2_index_by_partner if self.scope.primary_tier == 'HS2' else None
            ),
            sitc_index_by_partner=(
                self.sitc_index_by_partner if self.scope.primary_tier == 'SITC' else None
            ),
            countries=countries,
            hs4_codes=hs4_codes,
            logger=self.logger,
        )

    def _export_hs4_tci_charts(self, countries: list[str] | None, hs4_codes: list[str] | None):
        export_hs4_tci_charts(
            self._primary_tier_index_by_partner(),
            self._scope_export_dir(),
            tier_column=self.scope.primary_tier,
            countries=countries,
            tier_codes=hs4_codes,
            logger=self.logger,
        )

    def _export_word_summary(self, countries: list[str] | None, hs4_codes: list[str] | None):
        export_word_summary(
            self._primary_tier_index_by_partner(),
            self._scope_export_dir(),
            tier_column=self.scope.primary_tier,
            tier_labels=self.scope.primary_labels,
            countries=countries,
            tier_codes=hs4_codes,
            logger=self.logger,
        )

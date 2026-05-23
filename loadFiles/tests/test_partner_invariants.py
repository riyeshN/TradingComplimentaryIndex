"""
Regression test for partner-side / reporter-side RCA invariants.

Mirrors the runtime guard `TCICalculator._verify_partner_invariants()` so the
suite can be re-run after any refactor without exercising the full export
pipeline.
"""

from django.test import TestCase

from loadFiles.services.TCICalculator import TCICalculator
from loadFiles.services.scope import SCOPE_STRATEGIC, SCOPE_YANG
from loadFiles.models import HSSITCConcordance


TOLERANCE = 1e-9


def _run_pipeline_to_aggregation(calculator: TCICalculator) -> None:
    """Run the math half of the pipeline (load + compute every tier, no export).
    Identical to TCICalculator.run_indicators()."""
    calculator.run_indicators()


class PartnerInvariantsTest(TestCase):
    """
    Checks four ICT-scope invariants that must hold by definition of Balassa
    RCA. See `StrategicPartnerInvariantsTest` for the four extra HS2-tier
    invariants only present after the strategic-scope aggregation.

      1. HS6 `RCA Reporter Export` is identical across the China and US
         partner frames for matching `(Country, Year, Product code)`.
      2. HS6 `TCI_Drysdale_Garnaut == TCI_RCA_DG_Decomposition` within float
         tolerance (algebraic equality of two independent code paths).
      3. HS4 `RCA_Export_4digit` is identical across the China and US partner
         frames for matching `(Country, Year, HS4)`.
      4. HS4 `RCA_Import_4digit` is identical across reporters within each
         partner frame for matching `(Year, HS4)` — partner imports are
         partner-vs-world and must not depend on the reporter.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        calculator = TCICalculator()
        _run_pipeline_to_aggregation(calculator)
        cls.calculator = calculator

        partners = list(calculator.hs6_with_indicators_by_partner.keys())
        if len(partners) < 2:
            raise RuntimeError(
                "PartnerInvariantsTest needs at least 2 partner frames. "
                f"Loaded: {partners}"
            )
        cls.partner_a, cls.partner_b = partners[0], partners[1]

    def test_hs6_rca_reporter_export_partner_equal(self):
        hs6_a = self.calculator.hs6_with_indicators_by_partner[self.partner_a]
        hs6_b = self.calculator.hs6_with_indicators_by_partner[self.partner_b]
        joined = hs6_a[['Country', 'Year', 'Product code', 'RCA Reporter Export']].merge(
            hs6_b[['Country', 'Year', 'Product code', 'RCA Reporter Export']],
            on=['Country', 'Year', 'Product code'], how='inner',
            suffixes=(f'_{self.partner_a}', f'_{self.partner_b}'),
        )
        gap = (
            joined[f'RCA Reporter Export_{self.partner_a}']
            - joined[f'RCA Reporter Export_{self.partner_b}']
        ).abs().max()
        self.assertLessEqual(
            gap, TOLERANCE,
            f"HS6 RCA Reporter Export differs between {self.partner_a} and "
            f"{self.partner_b}: max gap {gap:.3g}",
        )

    def test_hs6_dg_equals_rca_decomposition(self):
        for partner_name, hs6_data in self.calculator.hs6_with_indicators_by_partner.items():
            gap = (
                hs6_data['TCI_Drysdale_Garnaut']
                - hs6_data['TCI_RCA_DG_Decomposition']
            ).abs().max()
            self.assertLessEqual(
                gap, TOLERANCE,
                f"HS6 TCI_Drysdale_Garnaut != TCI_RCA_DG_Decomposition for "
                f"{partner_name}: max gap {gap:.3g}",
            )

    def test_hs4_rca_export_partner_equal(self):
        hs4_a = self.calculator.hs4_index_by_partner[self.partner_a]
        hs4_b = self.calculator.hs4_index_by_partner[self.partner_b]
        joined = hs4_a[['Country', 'Year', 'HS4', 'RCA_Export_4digit']].merge(
            hs4_b[['Country', 'Year', 'HS4', 'RCA_Export_4digit']],
            on=['Country', 'Year', 'HS4'], how='inner',
            suffixes=(f'_{self.partner_a}', f'_{self.partner_b}'),
        )
        gap = (
            joined[f'RCA_Export_4digit_{self.partner_a}']
            - joined[f'RCA_Export_4digit_{self.partner_b}']
        ).abs().max()
        self.assertLessEqual(
            gap, TOLERANCE,
            f"HS4 RCA_Export_4digit differs between {self.partner_a} and "
            f"{self.partner_b}: max gap {gap:.3g}",
        )

    def test_hs4_rca_import_reporter_independent(self):
        for partner_name, hs4_data in self.calculator.hs4_index_by_partner.items():
            spread = (
                hs4_data.groupby(['Year', 'HS4'])['RCA_Import_4digit']
                .agg(lambda s: s.max() - s.min())
                .max()
            )
            self.assertLessEqual(
                spread, TOLERANCE,
                f"HS4 RCA_Import_4digit varies across reporters for partner "
                f"{partner_name}: max spread {spread:.3g}",
            )


class StrategicPartnerInvariantsTest(TestCase):
    """
    Strategic-scope (HS2 primary tier) invariants. Symmetric to the four ICT
    checks above plus two tier-additivity checks that only exist when the
    HS2 aggregation runs.

      5. HS2 `RCA_Export_2digit` identical across partner frames per
         `(Country, Year, HS2)`.
      6. HS2 `RCA_Import_2digit` identical across reporters within each
         partner frame per `(Year, HS2)`.
      7. Tier additivity: `TCI_DG_2digit == Σ TCI_DG_4digit within HS2`.
      8. Tier additivity: `Headline_Cij_DG == Σ TCI_DG_2digit per (Country, Year)`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        calculator = TCICalculator(scope=SCOPE_STRATEGIC)
        _run_pipeline_to_aggregation(calculator)
        cls.calculator = calculator

        partners = list(calculator.hs2_index_by_partner.keys())
        if len(partners) < 2:
            raise RuntimeError(
                "StrategicPartnerInvariantsTest needs at least 2 partner frames. "
                f"Loaded: {partners}"
            )
        cls.partner_a, cls.partner_b = partners[0], partners[1]

    def test_hs2_rca_export_partner_equal(self):
        hs2_a = self.calculator.hs2_index_by_partner[self.partner_a]
        hs2_b = self.calculator.hs2_index_by_partner[self.partner_b]
        joined = hs2_a[['Country', 'Year', 'HS2', 'RCA_Export_2digit']].merge(
            hs2_b[['Country', 'Year', 'HS2', 'RCA_Export_2digit']],
            on=['Country', 'Year', 'HS2'], how='inner',
            suffixes=(f'_{self.partner_a}', f'_{self.partner_b}'),
        )
        gap = (
            joined[f'RCA_Export_2digit_{self.partner_a}']
            - joined[f'RCA_Export_2digit_{self.partner_b}']
        ).abs().max()
        self.assertLessEqual(
            gap, TOLERANCE,
            f"HS2 RCA_Export_2digit differs between {self.partner_a} and "
            f"{self.partner_b}: max gap {gap:.3g}",
        )

    def test_hs2_rca_import_reporter_independent(self):
        for partner_name, hs2_data in self.calculator.hs2_index_by_partner.items():
            spread = (
                hs2_data.groupby(['Year', 'HS2'])['RCA_Import_2digit']
                .agg(lambda s: s.max() - s.min())
                .max()
            )
            self.assertLessEqual(
                spread, TOLERANCE,
                f"HS2 RCA_Import_2digit varies across reporters for partner "
                f"{partner_name}: max spread {spread:.3g}",
            )

    def test_hs2_cij_equals_sum_of_hs4_cij(self):
        for partner_name, hs2_data in self.calculator.hs2_index_by_partner.items():
            hs4_data = self.calculator.hs4_index_by_partner[partner_name].copy()
            hs4_data['HS2'] = hs4_data['HS4'].astype(str).str[:2]
            hs4_summed = (
                hs4_data.groupby(['Country', 'Year', 'HS2'])['TCI_DG_4digit']
                .sum().rename('HS4_Sum').reset_index()
            )
            joined = hs2_data[['Country', 'Year', 'HS2', 'TCI_DG_2digit']].merge(
                hs4_summed, on=['Country', 'Year', 'HS2'], how='inner',
            )
            gap = (joined['TCI_DG_2digit'] - joined['HS4_Sum']).abs().max()
            self.assertLessEqual(
                gap, TOLERANCE,
                f"HS2 Cij DG != sum of HS4 Cij within chapter for partner "
                f"{partner_name}: max gap {gap:.3g}",
            )

    def test_headline_cij_equals_sum_of_hs2_cij(self):
        for partner_name, hs2_data in self.calculator.hs2_index_by_partner.items():
            headline = self.calculator.headline_cij_by_partner[partner_name]
            hs2_summed = (
                hs2_data.groupby(['Country', 'Year'])['TCI_DG_2digit']
                .sum().rename('HS2_Sum').reset_index()
            )
            joined = headline[['Country', 'Year', 'Headline_Cij_DG']].merge(
                hs2_summed, on=['Country', 'Year'], how='inner',
            )
            gap = (joined['Headline_Cij_DG'] - joined['HS2_Sum']).abs().max()
            self.assertLessEqual(
                gap, TOLERANCE,
                f"Headline Cij DG != sum of HS2 Cij for partner "
                f"{partner_name}: max gap {gap:.3g}",
            )


class YangSitcInvariantsTest(TestCase):
    """
    Yang-scope (china→CCE, SITC tier) checks. Skipped automatically when the
    HSSITCConcordance table or the china_CCE data is absent. Yang is a
    single-reporter (china) / single-partner (CCE) run, so cross-partner
    invariants don't apply; what is checked is the definitional identity of
    the unweighted RCA product and that the pipeline runs end-to-end.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.available = HSSITCConcordance.objects.exists()
        cls.calculator = None
        if cls.available:
            calc = TCICalculator(scope=SCOPE_YANG, partner_names=('CCE',))
            calc.run_indicators()
            cls.calculator = calc

    def test_sitc_rca_product_is_definitional(self):
        if not self.available or self.calculator is None:
            self.skipTest("HSSITCConcordance / china_CCE data not loaded")
        sitc = self.calculator.sitc_index_by_partner.get('CCE')
        if sitc is None or sitc.empty:
            self.skipTest("No SITC output for CCE")
        gap = (
            sitc['TCI_RCA_Product_sitc']
            - sitc['RCA_Export_sitc'] * sitc['RCA_Import_sitc']
        ).abs().max()
        self.assertLessEqual(
            gap, TOLERANCE,
            f"SITC TCI_RCA_Product != RCA_Export × RCA_Import: max gap {gap:.3g}",
        )

    def test_sitc_sections_present(self):
        if not self.available or self.calculator is None:
            self.skipTest("HSSITCConcordance / china_CCE data not loaded")
        sitc = self.calculator.sitc_index_by_partner.get('CCE')
        if sitc is None or sitc.empty:
            self.skipTest("No SITC output for CCE")
        sections = set(sitc['SITC'].unique())
        # Expect the manufactured/primary sections at least; residual 9 may be sparse.
        self.assertTrue({'5', '6', '7', '8'}.issubset(sections),
                        f"Missing manufactured SITC sections; got {sorted(sections)}")

# Morning Summary — Session Recap

Single-page reference. Cold read; nothing assumed.

---

## TL;DR

The TCI pipeline now supports two analysis scopes:

- **ICT (Part II)** — 23 HS4 headings from UNCTAD ICT classification.
- **Strategic (Part I)** — 10 HS2 chapters from Freund et al. JIE strategic
  industries (chapter 98 dropped, no source data).

HS6 calculation is validated externally against **UN Comtrade** (≥ 93% within
5%) and **World Bank WITS** (Pearson r ≥ 0.98 for Korea + Japan). HS4 and HS2
aggregations use the same canonical-source-totals form, so RCA values are
**partner-independent on the import side and reporter-independent on the
export side by construction** — enforced at runtime *and* tested.

Test suite: **12/12 pass** (2 WITS RCA + 4 ICT invariants + 4 strategic
invariants + 2 Yang SITC invariants).

Yang (2023) cross-validation: manufactured-goods SITC sections reproduce within
2–3%; 66% of cells within 25%; direction matches all ten SITC sections. china→CEE
runs through the same pipeline. Two data fixes applied: (1) HS6→SITC mapping is
**vintage-aware** (one UN correspondence per HS edition, mapped by year) → SITC
coverage 0.06% unmapped (was 6%); (2) the CEE importer is the **sum of Yang's
exact 17 countries** (`build_cee_aggregate`), not TradeMap's opaque aggregate.
The residual primary-section gap (SITC0–4 ≈ ½ Yang) survives **all data fixes**.
Three data hypotheses ruled out: mapping (0.06% unmapped), country set (Yang's
exact 17), and **data source** — CEE fuel imports were measured directly against
the free Comtrade API and match (Poland/Hungary/Bulgaria ratio ≈1.00; the two
mismatches are Comtrade free-preview aggregation gaps, Comtrade *lower*, not
TradeMap). Decomposition: China's primary export RCAs are factually correct, the
world denominator is fixed by the matching manufactured sections, and CEE
imports = Comtrade — so our primary RCAs are correct and Yang's primary numbers
aren't reconstructible from real trade data. Residual is **Yang-side** (SITC
classification / RCA computation), not our index.

---

## What changed in this session

In order:

1. **HS4 partner-divergence bug fixed.** Lao 2024 HS4 8541 `RCA_Partner_Import`
   was 1.234842 (different from other reporters' 1.155793) because the old
   weight denominator was reporter-restricted. After fix, all reporters see
   the same 1.155793. Same bug existed in 317–593 cells per partner frame;
   all corrected.

2. **Scope abstraction.** New module `loadFiles/services/scope.py` with the
   `Scope` dataclass plus `SCOPE_ICT` and `SCOPE_STRATEGIC` constants. The
   pipeline takes a `Scope` argument; all scope-specific lists moved here.

3. **Strategic HS2 scope added.** 10 JIE chapters (28, 29, 30, 38, 84, 85, 87,
   88, 90, 93). Chapter 98 ("Special classification provisions") was on the
   JIE list but TradeMap has zero rows for it — dropped from `filter_codes`
   with a comment.

4. **HS2 aggregation tier.** New `_aggregate_hs4_to_hs2()` mirrors
   `_aggregate_hs6_to_hs4()` exactly. Three new helpers in
   `trade_data_loader.py` (`_world_hs2_totals`, `_partner_hs2_totals`,
   `_reporter_hs2_totals`) supply canonical-source HS2 totals on the
   `LoadedTradeData` bundle.

5. **Output subdirectories.** `data/TradeMapData/export/ict/` and
   `.../strategic/` keep the two scopes isolated; ICT outputs are byte-stable
   inside their new subdir.

6. **Exporters scope-aware.** Excel adds an `HS2 Summary` sheet for the
   strategic scope. Charts and the Word doc iterate the scope's primary tier
   (HS4 for ICT, HS2 for strategic).

7. **Yang (2023) cross-validation.** `validate_against_yang` runs the same
   `TCICalculator` for china→CEE (`scope=SCOPE_YANG, partner_names=('CCE',)`)
   and lines its SITC-section Cij up against Yang Table 3. HS6→SITC mapping in
   the `HSSITCConcordance` DB table.

8. **Runtime + test guards on RCA constancy.** `_verify_partner_invariants()`
   raises `ValueError` before any export file is written. Test classes
   `PartnerInvariantsTest` (4 ICT), `StrategicPartnerInvariantsTest` (4 HS2),
   and `YangSitcInvariantsTest` (2 SITC) re-test the invariants in CI.

9. **Documentation refresh.** README, validation_methodology, methodology
   doc, design_and_flow, pipeline diagram, CLAUDE.md all updated to reflect
   the dual-scope architecture.

---

## How to run (copy-paste)

```bash
# Default: ICT scope, all reporters, all years → export/ict/
conda run -n Econometrics_Deps python manage.py shell -c "from loadFiles.services.TCICalculator import TCICalculator; TCICalculator().run()"

# Strategic scope (JIE HS2 chapters) → export/strategic/
conda run -n Econometrics_Deps python manage.py shell -c "from loadFiles.services.TCICalculator import TCICalculator; from loadFiles.services.scope import SCOPE_STRATEGIC; TCICalculator(scope=SCOPE_STRATEGIC).run()"

# Both via HTTP — scope = 'ict' | 'strategic' | 'all'
conda run -n Econometrics_Deps python manage.py runserver
curl -X POST http://localhost:8000/loadFiles/calculate_tci -H 'Content-Type: application/json' -d '{"scope":"all"}'

# Tests
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.RCAFormulaValidationTest
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.PartnerInvariantsTest
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.StrategicPartnerInvariantsTest

# Yang side-by-side (China→CEE by SITC section). Concordance loads once.
conda run -n Econometrics_Deps python manage.py load_hs_sitc_concordance --csv data/reference_data/HS2022toSITC4ConversionAndCorrelationTables.xlsx
conda run -n Econometrics_Deps python manage.py validate_against_yang

# Full china→CEE workbook (same pipeline) → export/yang/CCE_TCI.xlsx
conda run -n Econometrics_Deps python manage.py shell -c "from loadFiles.services.TCICalculator import TCICalculator; from loadFiles.services.scope import SCOPE_YANG; TCICalculator(scope=SCOPE_YANG, partner_names=('CCE',)).run()"
```

---

## Validations in place

| Layer | What is checked | How | Tolerance | Status |
|---|---|---|---|---|
| Data source | HS6 trade values vs UN Comtrade | `ComtradeDataIntegrityTest` (free preview API) | ≥ 93% rows within 5% | Pass (Vietnam 97%, China 93%, US 99.8%) |
| Formula | HS6 Balassa RCA vs World Bank WITS | `RCAFormulaValidationTest` (Korea + Japan, HS 8542, 2022) | Pearson r ≥ 0.98 | Pass (Korea r = 0.998, Japan r = 0.989) |
| Internal | HS6 `TCI_Drysdale_Garnaut == TCI_RCA_DG_Decomposition` | `PartnerInvariantsTest`; pipeline-time | exact (gap ≤ 1e-9) | Pass |
| Partner consistency (ICT) | HS6 + HS4 RCAs invariant across partners / reporters | `PartnerInvariantsTest`, 4 tests; pipeline-time | gap ≤ 1e-9 | Pass |
| Partner consistency (Strategic) | HS2 RCAs + tier additivity | `StrategicPartnerInvariantsTest`, 4 tests; pipeline-time | gap ≤ 1e-9 | Pass |
| External cross-paper | Yang (2023) Table 3 (China→CEE by SITC) | `validate_against_yang` — runs the **same `TCICalculator` pipeline** (`scope=SCOPE_YANG, partner_names=('CCE',)`), no inline math | informational only | Manufactured sections (SITC5/6) within 2–3%; 66% of cells within 25%; direction matches all 10 sections; vintage mapping + CEE = Yang's exact 17 + source verified = Comtrade. Primary gap is Yang-side (classification/computation), all data hypotheses ruled out |

### Cij forms in every summary sheet (so the professor can pick the convention)

Each summary sheet (Country / HS4 / HS2 / SITC) now carries both:

- `TCI_Drysdale_Garnaut` — **weighted** (Σ HS6 DG, with `W_k/W`). Methodological primary; = Yang's *comprehensive* aggregate.
- `TCI_RCA_Product` — **unweighted** tier-level `RCA_x × RCA_m`. The per-product index published by Yang (2023, Table 3).

china→CEE (Yang) runs through the identical pipeline as ICT/strategic — same `_calculate_*` and aggregation methods, same invariant guards. `validate_against_yang` only reads pipeline output.

All eight strategic-scope invariants are also asserted at pipeline time via
`TCICalculator._verify_partner_invariants()` — any divergence aborts the run
with a `ValueError` *before* any output file is written. So a regression is
caught either by the test runner or by the next pipeline call.

---

## HS4 vs HS2 aggregation — same method

Both aggregations follow the same canonical-source pattern. No shortcut at
HS2, no separate codepath.

| Step | HS4 (ICT) | HS2 (Strategic) |
|---|---|---|
| Cij at tier | `Σ HS6 Cij within heading K` (Drysdale-Garnaut sum, preserves bilateral product matching) | `Σ HS6 Cij within chapter K` |
| RCA Export | `(Reporter Export HS4 Total / Reporter total) / (World Export HS4 Total / World total)` | `(Reporter Export HS2 Total / Reporter total) / (World Export HS2 Total / World total)` |
| RCA Import | `(Partner Import HS4 Total / Partner total) / (World Export HS4 Total / World total)` | `(Partner Import HS2 Total / Partner total) / (World Export HS2 Total / World total)` |
| Where HS4/HS2 totals come from | Precomputed in `trade_data_loader._world_hs4_totals` / `_partner_hs4_totals` / `_reporter_hs4_totals` from canonical DB tables — reporter-independent on world/partner side | Precomputed in `_world_hs2_totals` / `_partner_hs2_totals` / `_reporter_hs2_totals`, same pattern |

Because both tiers source their denominators from canonical DB rows (not from
each reporter's slice of the merged frame), `RCA_Import_*` is reporter-
independent and `RCA_Export_*` is partner-independent by construction.
This was the fix that resolved the Lao 2024 8541 incident.

Implementation references:

- `_aggregate_hs6_to_hs4` — `loadFiles/services/TCICalculator.py` (~lines 179–272)
- `_aggregate_hs4_to_hs2` — `loadFiles/services/TCICalculator.py` (~lines 274–352)

The two methods are line-by-line analogous; the only differences are the tier
column (`HS4` vs `HS2`), the totals frames merged in, and the result column
names (`_4digit` vs `_2digit`).

---

## Open items / next session

| Item | Notes |
|---|---|
| Configurable partner list | Currently hardcoded `('China', 'US')`. Add `partners` arg if Japan/Korea ever need to be importer roles too |
| Strategic Excel file size | `strategic/{partner}_TCI.xlsx` is ~110MB because of full HS6 across 10 chapters. Can suppress HS6 sheet for strategic if needed |
| Provenance column | Optional: add TSV source filename + load date to each HS6 row for auditability |

---

## File map (where each topic lives)

| Topic | File |
|---|---|
| Developer-facing project README | [`../README.md`](../README.md) |
| Economist-facing methodology | [`methodology_for_economists.md`](methodology_for_economists.md) |
| Validation procedure + §4 Yang cross-validation | [`validation_methodology.md`](validation_methodology.md) |
| Architecture, module map, dataflow | [`design_and_flow.md`](design_and_flow.md) |
| Pipeline diagram source + PNG | [`pipeline_flow.py`](pipeline_flow.py), [`pipeline_flow.png`](pipeline_flow.png) |
| Yang side-by-side discussion + CSV | [`yang_validation.md`](yang_validation.md), [`yang_validation.csv`](yang_validation.csv) |
| AI-coding instructions | [`../CLAUDE.md`](../CLAUDE.md) |
| Reference materials (Yang, ICT list, JIE paper, formula.pdf) | [`../readings/`](../readings/) |

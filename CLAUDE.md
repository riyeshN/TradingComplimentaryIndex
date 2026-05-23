# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Django web application that calculates **Trade Complementarity Index (TCI)** for bilateral trade relationships between countries (primarily China/US with Asian nations). Two TCI methodologies are implemented: Drysdale & Garnaut, and Revealed Comparative Advantage (RCA).

## Commands

```bash
# Use the Econometrics_Deps conda environment
conda run -n Econometrics_Deps python manage.py runserver
conda run -n Econometrics_Deps python manage.py migrate
conda run -n Econometrics_Deps python manage.py test
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.TestClassName
```

## API Endpoints

All endpoints are under `/loadFiles/`:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/loadFiles/update_reference_for_country_id` | Fetch country reference data from Comtrade → saves to CSV + DB |
| POST | `/loadFiles/fetch_trade_data` | Download bilateral trade data from Comtrade API |
| GET | `/loadFiles/load_trade_data_to_db` | Load all TradeMap TSV files into DB (run before extract) |
| GET/POST | `/loadFiles/calculate_tci` | Compute TCI from DB and export Excel files; POST body accepts optional `countries`, `hs4_codes`, and `scope` (`"ict"`, `"strategic"`, or `"all"`; default `"ict"`) |

**Workflow order:** `load_trade_data_to_db` → `calculate_tci`

### Adding New Year Data
Drop new TSV files into `data/TradeMapData/data/` and call `load_trade_data_to_db`.
Successfully loaded files are automatically moved to `data/TradeMapData/data/archive/` so only new/unprocessed files are ever in the main folder. The DB upserts on unique keys, so existing data is preserved and new rows are added.

**POST body for `calculate_tci`** (all fields optional; omit for full export):
```json
{
  "countries": ["Vietnam", "KoreaRepublic"],
  "hs4_codes": ["8542", "8541"]
}
```

**POST body for `fetch_trade_data`:**
```json
{
  "reporter": ["Vietnam", "Thailand"],
  "partner": ["US", "China"],
  "trade_type": "C",
  "frequency": "A",
  "year_period": [2020, 2021, 2022],
  "cmd_code": "AG6",
  "flow_code": "2"
}
```

## Architecture

### Data Sources
- **TradeMap TSV files** (`data/TradeMapData/data/`): ~65 tab-separated files with HS6 bilateral trade data (2001–2024). **Primary data source for the TCI pipeline.**
- **UN Comtrade API** (`loadFiles/services/ComtradeDownload.py`): Standalone utility (not part of the main pipeline) for fetching bilateral trade flows and country reference data via `comtradeapicall`. Used only on demand via the `update_reference_for_country_id` and `fetch_trade_data` endpoints.

### Core Processing Pipeline (`loadFiles/services/TCICalculator.py`)
Entry point: `TCICalculator().run()`

All four DB tables are queried directly in long format — no intermediate wide DataFrames or melt/pivot steps.

The pipeline is parameterised by a `Scope` record (`loadFiles/services/scope.py`). Two scopes are defined:
  - `SCOPE_ICT` — 23 HS4 headings of the UNCTAD ICT goods classification (Part II of the paper). `primary_tier = 'HS4'`.
  - `SCOPE_STRATEGIC` — 10 HS2 chapters from the JIE strategic-industry appendix (Part I of the paper). `primary_tier = 'HS2'`.

Output goes to `data/TradeMapData/export/{scope.name}/`. `TCICalculator(scope=...).run(...)` defaults to `SCOPE_ICT`.

1. `_load_from_db()` — delegates to `trade_data_loader.load_all()` (returns a `LoadedTradeData` bundle with HS4 *and* HS2 precomputed canonical-source totals plus TOTAL-row denominators)
2. `_filter_by_scope_and_year()` — restricts HS6 rows to `scope.filter_codes` (matched on the first `scope.filter_digits` characters of `Product code`) and years 2001–2024. Also drops vacated/re-used codes before their current meaning per `RESTRICTED_CODE_FIRST_VALID_YEAR` (currently `{'8524': 2022}`): HS 8524 was vacated in HS2007 (recorded media) and reintroduced in HS2022 (flat-panel display modules), so its 2007–2021 rows carry meaningless RCAs (near-zero world denominator) and mix two products — kept only for 2022+. Applies to every scope; the Word doc carries a matching "Data notes" paragraph
3. `_calculate_tci_drysdale_garnaut()` — HS6 DG: `(Xi_k/Xi) × (Mj_k/Mj) × (WX/WX_k)`
4. `_calculate_rca_and_tci_rca()` — HS6 Balassa RCAs; HS6 RCA-decomposition TCI (`TCI_RCA_DG_Decomposition`, internal cross-check); `Active_Pair` flag per row
5. `_aggregate_hs6_to_hs4()` — HS4 Cij = sum of HS6 Cij in heading (preserves bilateral product matching); HS4 RCA computed directly from canonical-source HS4 totals (`Reporter Export HS4 Total`, `Partner Import HS4 Total`, `World Export HS4 Total`)
6. `_aggregate_hs4_to_hs2()` — *(strategic scope only)* HS2 Cij = sum of HS6 Cij in chapter; HS2 RCA from canonical-source HS2 totals
7. `_calculate_headline_cij()` — Headline Cij per (reporter, partner, year): weighted `Headline_Cij_DG` (sum of HS6 DG) and unweighted `Headline_Cij_RCA_Product` (scope-level RCA_x × RCA_m)
8. `_verify_partner_invariants()` — runtime regression guard; raises `ValueError` on partner-side or tier-additivity divergence. Four checks for ICT scope (HS6 + HS4); eight for strategic scope (adds HS2 tier and tier-additivity)
9. `_export_excel(countries, hs4_codes)` — writes `{scope}/{partner}_TCI.xlsx`. ICT scope: 3 sheets (Country, HS4, HS6). Strategic scope: 4 sheets (Country, HS2, HS4, HS6). The `hs4_codes` filter applies to the tier and HS6 sheets only — the headline always reports the full scope number
10. `_export_hs4_tci_charts(countries, hs4_codes)` — writes one PNG per primary-tier code per partner: time series of DG Cij by reporter country
11. `_export_word_summary(countries, hs4_codes)` — writes `{scope}/RCA_Cij_Summary.docx`: method section plus one RCA/Cij year table per (reporter, primary-tier code) with US and China columns merged. Each table reports **both Cij forms** per partner — `Cij DG` (weighted) and `Cij RCA-prod` (unweighted RCA product) — i.e. 8 columns (Year, RCA export, RCA import US/CN, Cij DG US/CN, Cij RCA-prod US/CN). Layout mirrors `readings/RCA_Cij_Summary.docx`

**Key data structures (on `TCICalculator`):**
- `hs6_trade_data_by_partner` — long-format per partner ("China", "US")
- `hs6_with_indicators_by_partner` — HS6 frame with TCI/RCA columns
- `hs4_index_by_partner` — HS4-tier aggregate
- `hs2_index_by_partner` — HS2-tier aggregate (strategic scope only; empty for ICT)
- `headline_cij_by_partner` — one row per (reporter, year)

### DB Loading (`loadFiles/services/TradeMapLoader.py`)
Entry point: `TradeMapLoader().load()`
Parses all TSV files in `data/TradeMapData/data/`, upserts into DB, then archives each file to `data/TradeMapData/data/archive/`.

### Output Files (per partner country, under `data/TradeMapData/export/{scope}/`)

| Scope | File | Content |
|---|---|---|
| ict | `{partner}_TCI.xlsx` sheets `Country Summary`, `HS4 Summary`, `HS6 Detail` | 23 ICT HS4 headings, three-tier structure |
| ict | `{partner}_{HS4}_TCI_DG.png` | 46 charts (23 × 2 partners) |
| ict | `RCA_Cij_Summary.docx` | 368 reporter-HS4 tables + method section |
| strategic | `{partner}_TCI.xlsx` sheets `Country Summary`, `HS2 Summary`, `HS4 Summary`, `HS6 Detail` | 10 strategic HS2 chapters; full HS4 + HS6 detail inside |
| strategic | `{partner}_{HS2}_TCI_DG.png` | 20 charts (10 × 2 partners) |
| strategic | `RCA_Cij_Summary.docx` | 160 reporter-HS2 tables + method section |
| yang | `CCE_TCI.xlsx` sheets `Country Summary`, `SITC Summary`, `HS4 Summary`, `HS6 Detail` | china→CEE, SITC primary tier. Same pipeline (`scope=SCOPE_YANG, partner_names=('CCE',)`). Word doc skipped (single partner) |
| yang | `CCE_{SITC}_TCI_DG.png` | 10 SITC-section charts |

External cross-validation report:
- Yang (2023): [`docs/yang_validation.md`](docs/yang_validation.md) + `.csv`, via `python manage.py validate_against_yang`. China→CEE by SITC section; manufactured sections (SITC5/6) reproduce within 2–3%, 66% of cells within 25%. The residual primary-section gap (SITC0–4 ≈ ½ Yang) survives every data fix — HS→SITC mapping (vintage-aware, 0.06% unmapped), CEE country set (Yang's exact 17), and data source (CEE commodity imports verified equal to Comtrade) all ruled out — so the pipeline's primary RCAs are correct and the gap is **Yang-side** (SITC classification / RCA computation), not our index. Needs `china` data (`china_CCE.txt`), the rebuilt `CCE` aggregate (`build_cee_aggregate`), and the `HSSITCConcordance` table.

### Yang validation data + setup
- `china_CCE.txt` supplies the **China reporter exports** (to world + to CEE). China = exporter — opposite direction from the main ICT/strategic pipeline (where China/US are partners).
- **CEE importer = sum of Yang's exact 17 countries**, not TradeMap's opaque "CEE" aggregate (which under-captured commodity imports). One TradeMap "trade between China and {country}" file per country lives in `data/TradeMapData/cee_countries/` (kept out of the main TSV loader's path). Build the `CCE` partner-import rows with:
  ```bash
  python manage.py build_cee_aggregate            # sums imports-from-world over the 17 files → partner 'CCE'
  ```
  Re-run after any `TradeMapLoader` load that re-introduces a CCE import column. The 17: Albania, Bosnia and Herzegovina, Bulgaria, Croatia, Czech Republic, Estonia, Greece, Hungary, Latvia, Lithuania, Montenegro, North Macedonia, Poland, Romania, Serbia, Slovakia, Slovenia. With this exact group: 66% of cells within 25%, manufactured SITC5/6 within 2–3%. The primary-section gap (~½ Yang) survives the rebuild. **All three data hypotheses are ruled out** — HS→SITC mapping (vintage-aware, 0.06% unmapped), CEE country set (Yang's exact 17), and data source (CEE fuel imports verified equal to Comtrade: Poland/Hungary/Bulgaria ratio ≈1.00). Our primary RCAs are built from verified-correct inputs, so Yang's primary Cij are not reconstructible from real trade data — the residual is **Yang-side** (SITC classification / RCA computation), not our index.
- `HSSITCConcordance` model holds the **vintage-aware** HS6 → SITC Rev.4 mapping, keyed by `(product_code, hs_revision)`. Each year's HS6 is mapped through the HS edition in force that year (`trade_data_loader.hs_revision_for_year`: 2007–11→HS2007, 2012–16→HS2012, 2017–21→HS2017, 2022+→HS2022). Load **once per edition** (`xlrd` required for the .xls files):
  ```bash
  python manage.py load_hs_sitc_concordance --csv "data/reference_data/UN Comtrade Conversion table HS2007 to SITCRev4.xls" --revision 2007
  python manage.py load_hs_sitc_concordance --csv "data/reference_data/HS 2012 to SITC Rev.4 Correlation and conversion tables.xls" --revision 2012
  python manage.py load_hs_sitc_concordance --csv data/reference_data/HS2017toSITC4ConversionAndCorrelationTables.xlsx --revision 2017
  python manage.py load_hs_sitc_concordance --csv data/reference_data/HS2022toSITC4ConversionAndCorrelationTables.xlsx --revision 2022
  ```
  The loader locates HS/SITC columns by pattern (handles the heterogeneous UN file layouts) and replaces only the given revision's rows.

### Django App Structure
- **`loadFiles/views.py`** — 4 HTTP views wiring endpoints to services
- **`loadFiles/services/`** — business logic (Comtrade download, TradeMap processing)
- **`loadFiles/models.py`** — 6 DB models (see below; includes `HSSITCConcordance`)
- **`loadFiles/tests/`** — validation test suite (see below)
- **`loadFiles/management/commands/`** — supplementary CLI commands (`validate_comtrade_data`, `validate_rca_against_wits`, `validate_against_yang`, `load_hs_sitc_concordance`, `build_cee_aggregate`)
- **`TradingComplimentaryIndexRoot/`** — Django project config (settings, URL routing)
- **`docs/`** — formal methodology documentation for academic paper

### Test Suite (`loadFiles/tests/`)
Three test classes validate the pipeline before drawing conclusions:

| Class | What it validates | External source | Threshold |
|-------|-------------------|-----------------|-----------|
| `ComtradeDataIntegrityTest` | DB trade values match UN Comtrade source | Comtrade `previewFinalData` API (free, 500 rows) | ≥ 93% of rows within 5% tolerance |
| `RCAFormulaValidationTest` | Balassa RCA formula correctness at HS6 level | World Bank WITS CSV (`data/reference_data/`) | Pearson r ≥ 0.98 |
| `PartnerInvariantsTest` | RCA values consistent across partners (HS6 reporter RCA, HS4 reporter RCA, HS4 partner RCA) and HS6 DG = RCA-decomposition. Same checks also run at pipeline time via `TCICalculator._verify_partner_invariants()` | Internal | gap ≤ $10^{-9}$ |

Run all validation tests:
```bash
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.ComtradeDataIntegrityTest
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.RCAFormulaValidationTest
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.PartnerInvariantsTest
```

WITS CSV files required for RCA tests must be placed in `data/reference_data/`. Download from wits.worldbank.org → Advanced Query → Trade Outcomes Indicators → Revealed Comparative Advantage.

Supplementary management commands (`validate_comtrade_data`, `validate_rca_against_wits`) provide interactive output with mismatch tables — useful for investigation but the tests are the authoritative pass/fail check.

### Database Models (`loadFiles/models.py`)
Six models; the first five store trade data (DB is the source of truth for the TCI pipeline), the sixth holds the HS→SITC concordance for the Yang cross-validation:

| Model | Key fields | Purpose |
|-------|-----------|---------|
| `CountryReference` | comtrade_code, name, iso_alpha2 | UN Comtrade code ↔ country name lookup |
| `HSProduct` | product_code (pk), product_label | HS6 product code reference |
| `CountryExportToWorld` | reporter, product_code, year, value | Reporter's exports to world (Xi_k and Xi TOTAL) |
| `CountryExportToPartner` | reporter, partner, product_code, year, value | Bilateral exports; used only for Active Pair detection in 4-digit aggregation |
| `PartnerImportFromWorld` | partner, product_code, year, value | China/US imports from world (Mj_k and Mj TOTAL) |
| `WorldExport` | product_code, year, value | World exports by product (WX_k and WX TOTAL) |
| `HSSITCConcordance` | product_code (HS6), hs_revision, sitc_code, sitc_section; unique on (product_code, hs_revision) | Vintage-aware HS6 → SITC Rev.4 mapping (one row per HS edition) for the Yang cross-validation |

All value fields are in USD thousands. TOTAL rows are included for aggregate calculations.

### Formula Note
At HS6 level the pipeline computes Drysdale-Garnaut Cij directly (`TCI_Drysdale_Garnaut`) and the algebraically identical RCA-decomposition `RCA_x × RCA_m × (W_k/W)` (`TCI_RCA_DG_Decomposition`) as an internal cross-check — these two columns must agree to floating-point precision.

**Two Cij forms in every summary sheet** (Country/HS4/HS2/SITC), so the convention can be chosen downstream:
- `TCI_Drysdale_Garnaut` — Form A, **weighted** Σ HS6 DG (with `W_k/W`). Methodological primary; equals Yang's *comprehensive* aggregate `Σ RCA_x RCA_m (W_k/W)`.
- `TCI_RCA_Product` — **unweighted** tier-level `RCA_x × RCA_m`. The per-product index published by Yang (2023).

The china→CEE Yang comparison runs the **same** `TCICalculator` (`scope=SCOPE_YANG, partner_names=('CCE',)`) with a SITC aggregation tier (`_aggregate_to_sitc`, driven by `HSSITCConcordance`). HS6→SITC mapping is vintage-aware: `trade_data_loader._assign_sitc_section` merges each HS6 row against the concordance for the HS edition active in its year (`hs_revision_for_year`), shared by both the calculator's `_aggregate_to_sitc` and the loader's `_world/_partner/_reporter_sitc_totals` so numerator and denominator sections agree. `validate_against_yang` only reads pipeline output — no formula re-implementation.

HS4 Cij is computed as the **sum of HS6 Cij values within each heading** — not as a product of HS4 RCAs. The two formulations are not algebraically equal: the sum-of-HS6 form preserves bilateral HS6-level product matching, whereas the product-of-HS4-RCAs form (`(ΣX_k)(ΣM_k)`) treats a heading as complementary even when reporter and partner trade different HS6 codes within it. HS4 RCA is reported as an auxiliary heading-level specialisation metric only. See `README.md` and `docs/validation_methodology.md` for the full derivation.

HS4 RCA (auxiliary) is computed directly from the canonical-source HS4 totals (`PartnerImportFromWorld`, `CountryExportToWorld`, `WorldExport`), summed per `(partner, year, HS4)` / `(reporter, year, HS4)` / `(year, HS4)` respectively and broadcast across reporter rows. This is reporter-independent on the partner side and partner-independent on the reporter side by construction, so `RCA_Partner_Import` for the same `(partner, year, HS4)` is identical across every reporter — the property enforced by `PartnerInvariantsTest`.

### Python Environment
Conda environment: `Econometrics_Deps`
Run Django commands with: `conda run -n Econometrics_Deps python manage.py <command>`

## Dependencies

No `requirements.txt` exists yet. Key packages in use:
- `Django==4.2.19`
- `pandas`, `numpy`
- `comtradeapicall`
- `matplotlib`
- `openpyxl`
- `xlrd>=2.0.1` (reads the legacy `.xls` HS2007/HS2012 concordance files; install: `conda run -n Econometrics_Deps pip install xlrd`)
- `python-docx` (Word summary export; install: `conda run -n Econometrics_Deps pip install python-docx`)

## Data Directory Layout

```
data/
├── TradeMapData/
│   ├── data/       # Input TSV files from TradeMap
│   └── export/     # Generated Excel workbooks and PNG charts
└── reference_data/ # Country code reference files (HTS/HS code PDF), WITS RCA CSVs
docs/
└── validation_methodology.md  # Academic documentation of validation procedures
```

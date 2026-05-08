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
| GET/POST | `/loadFiles/calculate_tci` | Compute TCI from DB and export Excel files; POST body accepts optional `countries` and `hs4_codes` filters |

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

1. `_load_from_db()` — queries all 4 models, separates TOTAL rows as denominator lookups, precomputes reporter-independent HS4-level world totals (`World Export HS4 Total`), merges per partner (China, US) into `hs6_trade_data_by_partner`
2. `_filter_by_ict_scope_and_year()` — restricts to the 23 HS4 headings in the UNCTAD ICT goods classification (`HS4_ICT_HEADINGS`, HS 2022) and years 2001–2024
3. `_calculate_tci_drysdale_garnaut()` — HS6 DG: `(Xi_k/Xi) × (Mj_k/Mj) × (WX/WX_k)`
4. `_calculate_rca_and_tci_rca()` — HS6 Balassa RCAs; HS6 RCA-decomposition TCI (`TCI_RCA_DG_Decomposition`, internal cross-check); HS6 Tan Fen TCI (`TCI Tan Fen HS6` = RCA × RCA, no world-share factor); `Active_Pair` flag per row
5. `_aggregate_hs6_to_hs4()` — HS4 Cij = sum of HS6 Cij in heading (preserves bilateral product matching); HS4 RCA = weighted avg HS6 RCA with weight `W_k/W_HS4` (auxiliary; not used in HS4 Cij)
6. `_calculate_headline_cij()` — Headline Cij per (reporter, partner, year) = sum of HS6 Cij over the full ICT scope (DG eq. 2 applied directly); both DG and Tan Fen forms reported
7. `_export_excel(countries, hs4_codes)` — writes `{partner}_TCI.xlsx` with three sheets per partner: `Country Summary`, `HS4 Summary`, `HS6 Detail`. The `hs4_codes` filter applies to the HS4 and HS6 sheets only — the headline always reports the full ICT-scope number
8. `_export_hs4_tci_charts(countries, hs4_codes)` — writes one PNG per HS4 code per partner: time series of HS4 DG Cij by reporter country

**Key data structure:** `hs6_trade_data_by_partner` — dict keyed by partner name ("China", "US"), value is a long-format DataFrame with one row per (reporter, year, HS6 product). Also `hs4_index_by_partner` and `headline_cij_by_partner` dicts for downstream tiers.

### DB Loading (`loadFiles/services/TradeMapLoader.py`)
Entry point: `TradeMapLoader().load()`
Parses all TSV files in `data/TradeMapData/data/`, upserts into DB, then archives each file to `data/TradeMapData/data/archive/`.

### Output Files (per partner country)
One Excel workbook and one PNG per HS4 code, all written to `data/TradeMapData/export/`.

| File | Content |
|------|---------|
| `{partner}_TCI.xlsx` — sheet `Country Summary` | One row per (Country, Year) — Headline DG Cij, Headline Tan Fen Cij, Active HS6 pair count |
| `{partner}_TCI.xlsx` — sheet `HS4 Summary` | One row per (Country, Year, HS4) — DG Cij (sum of HS6), Tan Fen Cij (sum of HS6), HS4 RCA (export and import), trade totals, active pair count |
| `{partner}_TCI.xlsx` — sheet `HS6 Detail` | One row per (Country, Year, HS6 product) — all raw flows, RCA values, three TCI columns (DG, RCA-decomposition cross-check, Tan Fen), within-HS4 world share, active flag |
| `{partner}_{HS4}_TCI_DG.png` | Time-series line chart of HS4 DG Cij by reporter country |

### Django App Structure
- **`loadFiles/views.py`** — 4 HTTP views wiring endpoints to services
- **`loadFiles/services/`** — business logic (Comtrade download, TradeMap processing)
- **`loadFiles/models.py`** — 5 DB models (see below)
- **`loadFiles/tests/`** — validation test suite (see below)
- **`loadFiles/management/commands/`** — supplementary CLI validation commands
- **`TradingComplimentaryIndexRoot/`** — Django project config (settings, URL routing)
- **`docs/`** — formal methodology documentation for academic paper

### Test Suite (`loadFiles/tests/`)
Two test classes validate the pipeline before drawing conclusions:

| Class | What it validates | External source | Threshold |
|-------|-------------------|-----------------|-----------|
| `ComtradeDataIntegrityTest` | DB trade values match UN Comtrade source | Comtrade `previewFinalData` API (free, 500 rows) | ≥ 93% of rows within 5% tolerance |
| `RCAFormulaValidationTest` | Balassa RCA formula correctness at HS6 level | World Bank WITS CSV (`data/reference_data/`) | Pearson r ≥ 0.98 |

Run all validation tests:
```bash
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.ComtradeDataIntegrityTest
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.RCAFormulaValidationTest
```

WITS CSV files required for RCA tests must be placed in `data/reference_data/`. Download from wits.worldbank.org → Advanced Query → Trade Outcomes Indicators → Revealed Comparative Advantage.

Supplementary management commands (`validate_comtrade_data`, `validate_rca_against_wits`) provide interactive output with mismatch tables — useful for investigation but the tests are the authoritative pass/fail check.

### Database Models (`loadFiles/models.py`)
Five models store all trade data; DB is the source of truth for TCI pipeline:

| Model | Key fields | Purpose |
|-------|-----------|---------|
| `CountryReference` | comtrade_code, name, iso_alpha2 | UN Comtrade code ↔ country name lookup |
| `HSProduct` | product_code (pk), product_label | HS6 product code reference |
| `CountryExportToWorld` | reporter, product_code, year, value | Reporter's exports to world (Xi_k and Xi TOTAL) |
| `CountryExportToPartner` | reporter, partner, product_code, year, value | Bilateral exports; used only for Active Pair detection in 4-digit aggregation |
| `PartnerImportFromWorld` | partner, product_code, year, value | China/US imports from world (Mj_k and Mj TOTAL) |
| `WorldExport` | product_code, year, value | World exports by product (WX_k and WX TOTAL) |

All value fields are in USD thousands. TOTAL rows are included for aggregate calculations.

### Formula Note
At HS6 level the pipeline computes Drysdale-Garnaut Cij directly (`TCI_Drysdale_Garnaut`) and the algebraically identical RCA-decomposition `RCA_x × RCA_m × (W_k/W)` (`TCI_RCA_DG_Decomposition`) as an internal cross-check — these two columns must agree to floating-point precision. The Tan Fen (2024) form `RCA_x × RCA_m` (no world-share factor) is a distinct metric, reported separately as `TCI Tan Fen HS6`.

HS4 Cij is computed as the **sum of HS6 Cij values within each heading** — not as a product of HS4 RCAs. The two formulations are not algebraically equal: the sum-of-HS6 form preserves bilateral HS6-level product matching, whereas the product-of-HS4-RCAs form (`(ΣX_k)(ΣM_k)`) treats a heading as complementary even when reporter and partner trade different HS6 codes within it. HS4 RCA is reported as an auxiliary heading-level specialisation metric only. See `README.md` and `docs/validation_methodology.md` for the full derivation.

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

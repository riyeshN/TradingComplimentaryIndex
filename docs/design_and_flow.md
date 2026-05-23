# Design and Data Flow

Developer-facing description of how the TCI pipeline is wired together. For
the economic methodology see [`methodology_for_economists.md`](methodology_for_economists.md);
for the validation procedure see [`validation_methodology.md`](validation_methodology.md).

---

## Module Map

```
loadFiles/
├── views.py                          HTTP endpoints
├── models.py                         5 Django models
├── management/commands/              CLI validation tools
├── tests/                            Validation test suite
└── services/
    ├── ComtradeDownload.py           Comtrade API client (standalone)
    ├── TradeMapLoader.py             TSV → DB ingestion
    ├── trade_data_loader.py          DB → long-format DataFrames per partner
    ├── TCICalculator.py              Pure math; orchestrates pipeline
    └── exporters/
        ├── _filter.py                Shared scope filter (Country + HS4)
        ├── excel.py                  3-sheet workbook per partner
        ├── charts.py                 HS4 time-series PNGs
        └── word_summary.py           RCA_Cij_Summary.docx
```

Concern separation:

| File | Job | Touches DB? | Touches matplotlib? | Touches python-docx? |
|---|---|---|---|---|
| `TradeMapLoader.py` | Parse TSV, write rows | yes | no | no |
| `trade_data_loader.py` | Query and join | yes (read) | no | no |
| `TCICalculator.py` | RCA, Cij, aggregation | no | no | no |
| `exporters/excel.py` | xlsx output | no | no | no |
| `exporters/charts.py` | PNG output | no | yes | no |
| `exporters/word_summary.py` | docx output | no | no | yes |

`TCICalculator.run()` is the only orchestrator. Math methods inside it never
import I/O libraries.

---

## End-to-End Flow

![Pipeline flow](pipeline_flow.png)

The same flow in text form:

1. **Ingestion** — TradeMap TSV files in `data/TradeMapData/data/` are parsed by
   `TradeMapLoader.load()` and upserted into five Django models. Processed files
   are moved to `data/TradeMapData/data/archive/` so subsequent runs only pick
   up new files.

2. **Data assembly** — `trade_data_loader.load_per_partner()` queries the four
   trade tables, extracts TOTAL rows as per-year denominators, precomputes
   reporter-independent HS4 world totals, then merges everything into one
   long-format DataFrame per partner ("China", "US"). One row per
   `(reporter, year, HS6 product)`.

3. **Scope filter** — `_filter_by_ict_scope_and_year()` keeps only HS6 codes
   whose first four digits are in `HS4_ICT_HEADINGS` (the 23 UNCTAD ICT
   headings) and years 2001–2024.

4. **HS6 indicators** — two methods compute, per HS6 row:
   - `_calculate_tci_drysdale_garnaut()` → `TCI_Drysdale_Garnaut`
   - `_calculate_rca_and_tci_rca()` → `RCA Reporter Export`, `RCA Partner Import`,
     `TCI_RCA_DG_Decomposition` (internal cross-check), `Active_Pair` flag

5. **HS4 aggregation** — `_aggregate_hs6_to_hs4()` builds per (reporter, year, HS4):
   - HS4 Cij DG (weighted) = **sum** of HS6 `TCI_Drysdale_Garnaut`
   - HS4 RCA  = canonical-source HS4 totals via Balassa (`RCA_Export_4digit`, `RCA_Import_4digit`)
   - HS4 Cij RCA product (unweighted) = `RCA_Export_4digit × RCA_Import_4digit`

6. **Headline** — `_calculate_headline_cij()` sums HS6 Cij across the full
   ICT scope, per (reporter, year). One row per country-year.

7. **Exports** — three exporters consume the same indicator DataFrames:
   - `export_excel(...)` → `{partner}_TCI.xlsx` with sheets `Country Summary`,
     `HS4 Summary`, `HS6 Detail`
   - `export_hs4_tci_charts(...)` → one PNG per (partner, HS4) time series
   - `export_word_summary(...)` → `RCA_Cij_Summary.docx` (method section +
     one table per reporter × HS4 with US and China columns merged; each table
     reports both Cij forms per partner — DG weighted and RCA-product unweighted)

   Each exporter accepts optional `countries` and `hs4_codes` filters; the
   filter is applied uniformly via `exporters._filter.filter_scope`. The
   `hs4_codes` filter does **not** affect the headline sheet — that always
   reports the full ICT-scope number.

---

## State Held on the `TCICalculator` Instance

| Attribute | Built by step | Shape (rows) | Used by |
|---|---|---|---|
| `hs6_trade_data_by_partner`     | 2, 3 | partner × HS6 × reporter × year | steps 4–6 |
| `hs6_with_indicators_by_partner`| 5    | adds Cij/RCA columns           | step 7 (Excel HS6 sheet) |
| `hs4_index_by_partner`          | 5    | partner × HS4 × reporter × year | step 7 (Excel HS4 sheet, charts, Word) |
| `headline_cij_by_partner`       | 6    | partner × reporter × year       | step 7 (Excel Country Summary) |

All four are dict keyed by partner name (`"China"`, `"US"`).

---

## Three-Tier Numerical Invariants

Maintained by construction; verified at runtime.

| Invariant | Where |
|---|---|
| HS6: `TCI_Drysdale_Garnaut == TCI_RCA_DG_Decomposition` | algebraic equality, two independent code paths in `_calculate_*` |
| HS4 Cij = sum of HS6 Cij | groupby `sum` in `_aggregate_hs6_to_hs4` |
| Headline Cij = sum of HS6 Cij over scope = sum of HS4 Cij | groupby `sum` in `_calculate_headline_cij` |

A change that breaks any of these signals a regression. The first invariant is
also the basis of validation §3 in `validation_methodology.md`.

---

## Entry Points

| Use case | Path |
|---|---|
| HTTP — calculate TCI | `POST /loadFiles/calculate_tci` (`views.py` → `TCICalculator().run(...)`) |
| HTTP — load TSV files into DB | `GET /loadFiles/load_trade_data_to_db` (`views.py` → `TradeMapLoader().load()`) |
| Shell — calculate TCI | `python manage.py shell -c "from loadFiles.services.TCICalculator import TCICalculator; TCICalculator().run()"` |
| Test — RCA correctness | `python manage.py test loadFiles.tests.RCAFormulaValidationTest` |
| Test — Comtrade data integrity | `python manage.py test loadFiles.tests.ComtradeDataIntegrityTest` |

---

## Adding a New Output Format

Pattern: write a function in `loadFiles/services/exporters/` that takes the
indicator dicts plus `(export_dir, countries, hs4_codes, logger)`, do the
filtering via `_filter.filter_scope`, and write to disk. Export the function
from `exporters/__init__.py`. Add a thin delegating method on `TCICalculator`
and call it from `run()`.

The existing three exporters (`excel.py`, `charts.py`, `word_summary.py`) are
templates — each is self-contained and depends only on its specific output
library.

---

## Regenerating the Flow Diagram

```bash
conda run -n Econometrics_Deps python docs/pipeline_flow.py
```

The script writes `docs/pipeline_flow.png`. Source is checked in so the diagram
stays in sync with the modules it describes.

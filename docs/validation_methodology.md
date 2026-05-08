# Data and Methodology Validation

Two external validations and one internal consistency check confirm the HS 6-digit calculation layer of the TCI pipeline.

| # | What is checked | Source | Threshold |
|---|---|---|---|
| 1 | DB trade values match UN Comtrade | Comtrade API | ≥ 93% within 5% |
| 2 | RCA formula matches World Bank WITS | WITS CSV | Pearson $r \ge 0.98$ |
| 3 | DG TCI vs RCA-decomposition TCI agree | Internal | Exact equality |

If 1–3 pass, all downstream outputs are correct by construction.

---

## Running the Pipeline

```bash
conda run -n Econometrics_Deps python manage.py runserver
```

| Step | Endpoint | Effect |
|---|---|---|
| 1 | `GET /loadFiles/load_trade_data_to_db` | Parse TSV files in `data/TradeMapData/data/` into DB; archive processed files |
| 2 | `POST /loadFiles/calculate_tci` | Run `TCICalculator().run()`; export Excel + PNG to `data/TradeMapData/export/` |

Optional POST body for step 2: `{"countries": ["Vietnam"], "hs4_codes": ["8542"]}`.

**Where to find each metric:**

| Metric | File | Sheet | Column |
|---|---|---|---|
| Reporter HS6 RCA | `{partner}_TCI.xlsx` | `HS6 Detail` | `RCA_Reporter_Export` |
| Partner HS6 RCA | `{partner}_TCI.xlsx` | `HS6 Detail` | `RCA_Partner_Import` |
| HS6 TCI — Drysdale-Garnaut | `{partner}_TCI.xlsx` | `HS6 Detail` | `TCI_Drysdale_Garnaut` |
| HS6 TCI — RCA decomposition | `{partner}_TCI.xlsx` | `HS6 Detail` | `TCI_RCA` |
| World share $W_k/W$ | `{partner}_TCI.xlsx` | `HS6 Detail` | `Proportion_World_Trade` |

Internal consistency (§3) verified by spot-checking any non-zero row: `TCI_Drysdale_Garnaut == TCI_RCA` to floating-point precision.

Source code:

| Quantity | File | Method |
|---|---|---|
| RCA (export and import) | `loadFiles/services/TCICalculator.py` | `_calculate_rca_and_tci_rca()` |
| TCI Drysdale-Garnaut | `loadFiles/services/TCICalculator.py` | `_calculate_tci_drysdale_garnaut()` |
| TCI RCA-decomposition | `loadFiles/services/TCICalculator.py` | `_calculate_rca_and_tci_rca()` |

---

## 1 — Trade Data Integrity

Verifies `CountryExportToWorld` (reporter exports) and `PartnerImportFromWorld` (China and US imports) match values returned by `comtradeapicall.previewFinalData`. DB stores USD thousands; Comtrade USD — converted before comparison.

**Tolerance.** A row matches if within 5% of the Comtrade value.

**Sample size.** Free Comtrade API caps responses at 500 rows per request. A full reporter-year HS6 dataset is 4,000–6,000 rows, so the test is a spot check, not an exhaustive audit.

```bash
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.ComtradeDataIntegrityTest
```

Sample output:

```
Products compared (in both):   500
Matched within 5%:             485 (97.0%)
Mismatched (>5% diff):          15
Only in DB (not in Comtrade): 5737  ← expected; DB has full HS6 universe
```

Mismatches concentrate on values < USD 10,000 — caused by integer truncation (sub-USD 500 stored as 0 in USD thousands) and TradeMap/Comtrade vintage differences. Neither is a systematic error.

> Diagnostic-only command: `validate_comtrade_data` prints a per-row mismatch table.

---

## 2 — RCA Formula Correctness

Compares pipeline RCA against WITS published RCA at HS6 for matching reporter-year-product rows.

**Formula (Balassa 1965):**

$$
\mathrm{RCA}_{i,k} \;=\; \frac{X_{i,k} / X_{i}}{W_{k} / W}
$$

- $X_{i,k}$ — reporter $i$ exports of product $k$
- $X_{i}$ — reporter $i$ total exports
- $W_{k}$ — world exports of product $k$
- $W$ — total world exports

Pipeline column `RCA Reporter Export` in `hs6_trade_data_by_partner`.

**WITS download.** wits.worldbank.org → Advanced Query → Trade Outcomes Indicators → indicator = Revealed Comparative Advantage, partner = World, products = All HS6 → save CSV to `data/reference_data/`.

Test files:

| File | Reporter | Year |
|---|---|---|
| `DataJobID-3071537_3071537_allItems.csv` | Korea, Rep. | 2022 |
| `DataJobID-3071538_3071538_japan8542.csv` | Japan | 2022 |

```bash
conda run -n Econometrics_Deps python manage.py test loadFiles.tests.RCAFormulaValidationTest
```

Sample output:

```
HS6 products in both:       5
Pearson correlation:     0.9979
Mean absolute % diff:   10.27%
```

WITS uses HS 2022; TradeMap files may use earlier revisions. Product 854239 shows ~32% discrepancy across reporters — a known revision-boundary mismatch, not a formula error. Other products fall within 0.1–8.5%.

> Diagnostic-only command: `validate_rca_against_wits` prints a ranked discrepancy table.

---

## 3 — TCI Formula Internal Consistency

Two algebraically equivalent forms of the HS6 Trade Complementarity Index are computed independently. Comparing them detects implementation regressions.

**Drysdale-Garnaut (1982) form** — `_calculate_tci_drysdale_garnaut()`, column `TCI_Drysdale_Garnaut`:

$$
C_{ij,k} \;=\; \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{W}{W_{k}}
$$

$C_{ij,k} > 1$ → reporter export specialization in $k$ matches partner import specialization.

**RCA-decomposition form** — `_calculate_rca_and_tci_rca()`, column `TCI Using RCA`:

$$
C_{ij,k} \;=\; \mathrm{RCA}_{x,i,k} \cdot \mathrm{RCA}_{m,j,k} \cdot \frac{W_{k}}{W}
$$

with $\mathrm{RCA}_{x,i,k} = (X_{i,k}/X_{i}) / (W_{k}/W)$ and $\mathrm{RCA}_{m,j,k} = (M_{j,k}/M_{j}) / (W_{k}/W)$.

**Equivalence:**

$$
\mathrm{RCA}_{x} \cdot \mathrm{RCA}_{m} \cdot \tfrac{W_{k}}{W}
\;=\; \tfrac{X_{i,k}}{X_{i}} \cdot \tfrac{M_{j,k}}{M_{j}} \cdot \tfrac{W}{W_{k}}
\;=\; C_{ij,k}^{\,\mathrm{DG}}
$$

The columns must agree by construction. A divergence indicates an implementation bug (NaN handling, divide-by-zero, dataflow regression). The check does **not** validate methodology or data — those rest on §1 and §2.

**Tan Fen (2024) variant — not implemented.** $C_{k}^{\,\mathrm{Tan}} = \mathrm{RCA}_{x} \cdot \mathrm{RCA}_{m}$, no world-share factor. Differs from DG by $W/W_{k}$ — niche products score larger. Recorded for completeness; suited to single-product analysis.

---

## Results

| Run | Country | Year | Flow | n | Result | Note |
|---|---|---|---|---|---|---|
| 1a | Vietnam | 2022 | X | 500 | 97.0% match | 15 mismatches, all < USD 10k (integer truncation) |
| 1b | China | 2022 | M | 499 | 93.2% match | 34 mismatches, all sub-USD 600 stored as 0 |
| 1c | United States | 2022 | M | 500 | 99.8% match | 1 rounding artefact (HS 292214) |
| 2a | Korea, Rep. | 2022 | — | 5 (HS 8542) | $r = 0.998$ | 854239 HS revision mismatch only |
| 2b | Japan | 2022 | — | 5 (HS 8542) | $r = 0.989$ | Same 854239 pattern |

All passing. HS6 layer validated.

---

## HS 4-digit Aggregation

The HS 4-digit layer is built by a three-stage pipeline that propagates the validated HS 6-digit RCA upward without re-introducing data dependencies.

### Stage 1 — HS 6-digit RCA

Computed as defined in §2 above. Each HS 6-digit line yields one $\mathrm{RCA}_{x,i,k}$ for the reporter and one $\mathrm{RCA}_{m,j,k}$ for the partner.

By construction, RCA is zero for any HS 6-digit line where the reporter does not export the product to the world or where the partner does not import the product from the world. Such lines therefore contribute nothing to subsequent aggregation.

### Stage 2 — HS 6-digit → HS 4-digit RCA aggregation

The HS 4-digit RCA can be written in two algebraically identical forms:

**Form A — sum trade values, then apply Balassa once**

$$
\mathrm{RCA}_{x,i,K} \;=\; \frac{\bigl(\sum_{k \in K} X_{i,k}\bigr) / X_{i}}{\bigl(\sum_{k \in K} W_{k}\bigr) / W}
$$

where $K$ denotes the HS 4-digit heading and the sum runs over all HS 6-digit codes belonging to it. The same expression with $M$ in place of $X$ gives $\mathrm{RCA}_{m,j,K}$.

**Form B — weighted average of HS 6-digit RCA values**

$$
\mathrm{RCA}_{x,i,K} \;=\; \sum_{k \in K} \mathrm{RCA}_{x,i,k} \cdot \frac{W_{k}}{\sum_{k \in K} W_{k}}
$$

Weight = product $k$'s share of world trade within the HS 4-digit heading. Form B exposes the dependence on HS 6-digit RCA explicitly; Form A is computationally simpler.

**Equivalence:**

$$
\sum_{k \in K} \mathrm{RCA}_{x,i,k} \cdot \frac{W_{k}}{\sum W_{k}}
\;=\; \sum_{k \in K} \frac{X_{i,k}/X_{i}}{W_{k}/W} \cdot \frac{W_{k}}{\sum W_{k}}
\;=\; \frac{W \sum_{k} X_{i,k}}{X_{i} \sum_{k} W_{k}}
\;=\; \frac{(\sum X_{i,k})/X_{i}}{(\sum W_{k})/W}
$$

Identical to Form A.

**Implementation.** This pipeline uses Form A — `_aggregate_hs6_to_hs4()` in `loadFiles/services/TCICalculator.py` sums HS 6-digit trade values (`Total_Reporter_Export`, `Total_Partner_Import`, `Total_World_Export_k`) within each HS 4-digit heading and then applies the Balassa formula once. Form B is documented for interpretive clarity; the result is identical.

**Validation by inheritance.** HS 6-digit RCA is validated externally against WITS (§2). HS 4-digit RCA is a deterministic arithmetic function of HS 6-digit inputs (Form A) — equivalently, a deterministic weighted average of HS 6-digit RCA (Form B). No additional external validation is required.

### Stage 3 — HS 4-digit Cij and headline Cij

Both Cij outputs are computed by summing HS 6-digit Cij values over the appropriate scope:

**HS 4-digit Cij** (one per reporter, partner, year, heading $K$):

$$
C_{ij,K} \;=\; \sum_{k \in K} \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{W}{W_{k}}
$$

**Headline Cij** (one per reporter, partner, year):

$$
C_{ij} \;=\; \sum_{k \in \mathrm{scope}} \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{W}{W_{k}}
$$

This is Drysdale-Garnaut (1982, eq. 2) applied at heading level and at country-pair level respectively.

**Why sum HS 6-digit Cij rather than compute Cij from HS 4-digit RCA values.** The two forms

$$
\sum_{k \in K} \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{W}{W_{k}}
\quad\text{vs.}\quad
\mathrm{RCA}_{x,i,K} \cdot \mathrm{RCA}_{m,j,K} \cdot \frac{W_{K}}{W}
$$

are **not** algebraically equal. The first reduces to a sum of products $\sum X_{i,k} M_{j,k}$; the second reduces to a product of sums $(\sum X_{i,k})(\sum M_{j,k})$. The second form records a heading as complementary whenever both the reporter and the partner trade *some* HS 6-digit code under that heading, even when they trade *different* codes. The sum-of-products form counts only the HS 6-digit lines where both sides have non-zero world flows of the same product. Because Drysdale-Garnaut Cij is fundamentally about product-level alignment, this pipeline uses the sum-of-products form.

**Tan Fen (2024) variant — secondary, for sensitivity comparison:**

$$
C_{K}^{\,\mathrm{Tan}} \;=\; \sum_{k \in K} \mathrm{RCA}_{x,i,k} \cdot \mathrm{RCA}_{m,j,k}
$$

Differs from the Drysdale-Garnaut form by the absence of the $W/W_{k}$ factor inside the sum.

**Auxiliary HS 4-digit RCA values.** The Stage 2 outputs $\mathrm{RCA}_{x,i,K}$ and $\mathrm{RCA}_{m,j,K}$ are exported as their own columns to describe heading-level specialisation. They are not consumed in the computation of $C_{ij,K}$.

### Interpretation

Cij as defined here measures **potential** bilateral complementarity — the alignment between reporter $i$'s export specialization (against world) and partner $j$'s import specialization (against world). It is not a measure of realised bilateral trade flows. A separate index (such as the Trade Intensity Index) would be required for that purpose.

---

## Scope

This document covers the HS 6-digit and HS 4-digit calculation layers. The choice of Drysdale-Garnaut versus Tan Fen at the HS 4-digit level, and the policy interpretation of resulting values, are the subject of separate methodological review.

# Trade Complementarity between Indo-Pacific Economies and the United States and China

## Methodology and Data — Non-Technical Overview

This document describes, for an economist reader, what the project measures, what data
it uses, and how the indices are constructed. No software details are included.

---

## 1. Research Question

For each year between 2001 and 2024, how complementary are the export specialisations of
the Indo-Pacific economies with the import demands of the United States and the People's
Republic of China, in the goods that constitute the modern information and communication
technology (ICT) trade?

A high complementarity index between two economies is interpreted, following Frankel,
Stein and Wei (1995), as evidence that the two economies are "natural trading partners"
in the absence of preferential arrangements: country *i* exports the products that
country *j* needs to import, and vice versa.

---

## 2. Reporters, Partners, and Coverage

| Element | Coverage |
|---|---|
| Reporters (country *i*) | Indo-Pacific economies: Australia, ASEAN-10, India, Japan, Republic of Korea, New Zealand, Taiwan |
| Partners (country *j*) | United States and China, treated separately |
| Period | Annual, 2001 to 2024 |
| Product scope | UNCTAD Information and Communication Technology goods classification (HS 2022) — 23 HS 4-digit headings, 107 HS 6-digit codes |
| Trade flow granularity | HS 6-digit, the most disaggregated level published in standard databases |

The ICT scope follows the UNCTAD list (see *readings/ICTList.docx*) and includes
data-processing machines (HS 8471), telecommunication equipment (HS 8517), semiconductor
devices (HS 8541), electronic integrated circuits (HS 8542), monitors and projectors
(HS 8528), and twenty further headings. The complete list of HS 4-digit headings is in
the project [`README.md`](../README.md) under *Scope*.

---

## 3. Data Sources

| Source | Purpose | Identifier |
|---|---|---|
| ITC Trade Map | Primary trade values — bilateral exports, imports, and world flows by HS 6-digit code, 2001–2024 | https://www.trademap.org |
| UN Comtrade | Independent verification of trade values | https://comtrade.un.org |
| World Bank WITS | Independent verification of Balassa Revealed Comparative Advantage scores at HS 6-digit | https://wits.worldbank.org |
| UNCTAD ICT classification | Definition of the ICT goods scope, HS 2022 | https://unctadstat.unctad.org |

All trade values are stored in USD thousands. For each (reporter, year) the database
contains the TOTAL across all products (used as denominators in share calculations).

---

## 4. Variable Definitions

The notation follows the published Drysdale-Garnaut (1982) formulation.

| Symbol | Meaning | Unit |
|---|---|---|
| $X_{i,k}$ | Country $i$'s exports of HS 6-digit commodity $k$ to the world | USD thousands |
| $X_{i}$ | Country $i$'s total exports to the world (all commodities) | USD thousands |
| $M_{j,k}$ | Country $j$'s imports of commodity $k$ from the world | USD thousands |
| $M_{j}$ | Country $j$'s total imports from the world (all commodities) | USD thousands |
| $T_{k}$, equivalently $W_{k}$ | World trade (total exports) of commodity $k$ | USD thousands |
| $T$, equivalently $W$ | World total trade (all commodities) | USD thousands |
| $K$ | An HS 4-digit heading. The set of HS 6-digit codes belonging to it is $\{k \in K\}$ | — |

Bilateral exports $X_{i \to j, k}$ (country $i$'s exports of $k$ to partner $j$ specifically)
are stored but **not** used in the indices below. The Drysdale-Garnaut framework measures
*potential* complementarity from world-level specialisation patterns; bilateral flows
would be the input to a Trade Intensity Index, which is a different measure.

---

## 5. The Three Indices Computed

### 5.1 Balassa Revealed Comparative Advantage at HS 6-digit

For each commodity $k$, two RCAs are computed:

$$
\mathrm{RCA}_{x,i,k} \;=\; \frac{X_{i,k}/X_{i}}{T_{k}/T}
\qquad\qquad
\mathrm{RCA}_{m,j,k} \;=\; \frac{M_{j,k}/M_{j}}{T_{k}/T}
$$

$\mathrm{RCA}_{x,i,k}$ exceeds 1 when country $i$'s share of its own export basket
allocated to product $k$ is greater than world trade's share allocated to $k$ — that is,
$i$ is *specialised* in exporting $k$. The import RCA is interpreted analogously for
country $j$'s import demand.

By construction, these RCAs are zero whenever the relevant trade flow is zero.

### 5.2 Trade Complementarity at HS 6-digit (Drysdale-Garnaut, 1982)

For each commodity $k$:

$$
C_{ij,k} \;=\; \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{T}{T_{k}}
$$

This is algebraically equivalent to:

$$
C_{ij,k} \;=\; \mathrm{RCA}_{x,i,k} \cdot \mathrm{RCA}_{m,j,k} \cdot \frac{T_{k}}{T}
$$

Both forms are computed independently and reported alongside one another. Their equality
to floating-point precision serves as an internal arithmetic check on the implementation
(it is not an empirical validation).

### 5.3 Trade Complementarity at HS 4-digit

For an HS 4-digit heading $K$:

$$
C_{ij,K} \;=\; \sum_{k \in K} C_{ij,k}
\;=\; \sum_{k \in K} \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{T}{T_{k}}
$$

The HS 4-digit complementarity is the sum of the HS 6-digit complementarity values within
that heading. It is *not* computed by applying the Drysdale-Garnaut formula to HS 4-digit
totals. Doing so would yield a mathematically different number that records a heading as
complementary even when the reporter and partner trade entirely different HS 6-digit
products inside it. The sum-of-HS6 form preserves the bilateral product alignment
captured at the most granular level. (See the project [`README.md`](../README.md) for
a worked numerical example.)

**Heading-weighted-average form (reported alongside).** Because the sum grows with the
number of HS 6-digit lines in a heading and with the heading's trade size, it is not
directly comparable across headings. A weighted-average form is therefore also reported
(column `TCI_DG_WeightedAvg`):

$$
\overline{C}_{ij,K} \;=\; \sum_{k \in K} \frac{T_k}{T_K}\,\mathrm{RCA}_{x,k}\,\mathrm{RCA}_{m,k}
\;=\; \frac{T}{T_K}\sum_{k \in K} C_{ij,k},
\qquad T_K=\sum_{k\in K}T_k.
$$

The averaged quantity is the unweighted per-product complementarity
$\mathrm{RCA}_{x,k}\mathrm{RCA}_{m,k}$ (without the $T_k/T$ factor), and the world-trade
weight $T_k/T_K$ is applied once. Equivalently, it is the heading Drysdale-Garnaut sum
scaled by $T/T_K$. This puts every heading on the same scale (comparable to an HS 6-digit
value). It preserves bilateral alignment (it sums per-product terms, not
$(\sum X)(\sum M)$), so it is distinct from the product-of-HS4-RCAs form above. Trade-off:
it is **not additive** — it does not sum to the headline. Use the sum form ($C_{ij,K}$)
for the headline-consistent index and the weighted average ($\overline{C}_{ij,K}$) for
comparing headings on a common scale.

### 5.4 Headline Trade Complementarity Index

For each (reporter, partner, year):

$$
C_{ij} \;=\; \sum_{k \in \mathrm{ICT\ scope}} C_{ij,k}
\;=\; \sum_{k \in \mathrm{ICT\ scope}} \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{T}{T_{k}}
$$

This is Drysdale-Garnaut equation (2) applied directly across the 107 HS 6-digit codes
of the ICT scope. By the additivity of the sum-of-HS6 construction, $C_{ij}$ equals
the sum of $C_{ij,K}$ across all 23 HS 4-digit headings, which equals the sum of all
HS 6-digit Cij in scope.

### 5.5 Auxiliary metric — HS 4-digit RCA

For interpretive purposes, RCA is also reported at HS 4-digit level:

$$
\mathrm{RCA}_{x,i,K} \;=\; \sum_{k \in K} \mathrm{RCA}_{x,i,k} \cdot \frac{T_{k}}{\sum_{k \in K} T_{k}}
$$

A weighted average of the HS 6-digit RCAs, with weights equal to each HS 6-digit code's
share of world trade *within its parent HS 4-digit heading*. Algebraically identical to
applying the Balassa formula to HS 4-digit totals. Reported as a heading-level
specialisation summary; not used in the calculation of $C_{ij,K}$.

### 5.6 Unweighted RCA product — secondary

The pipeline also reports the tier-level Balassa RCA product without the
world-trade-share factor:

$$
C_{K}^{\,\mathrm{RCA}} \;=\; \mathrm{RCA}_{x,i,K} \cdot \mathrm{RCA}_{m,j,K}
$$

This is **not** algebraically equivalent to Drysdale-Garnaut — the two differ by the
factor $T/T_{K}$. It is the per-product index published by Yang (2023, Table 3) and
is reported as `TCI_RCA_Product` alongside the weighted Drysdale-Garnaut form at every
tier so the convention can be chosen downstream. Drysdale-Garnaut remains the primary
index, following the original 1982 definition.

A step-by-step derivation of why the two forms diverge is in
[`readings/formula.pdf`](../readings/formula.pdf).

---

## 6. Interpretation

| Range of $C_{ij}$ | Interpretation (following the Drysdale-Garnaut convention) |
|---|---|
| $C_{ij} > 1$ | Reporter $i$'s export specialisation matches partner $j$'s import specialisation. The two countries are "natural trading partners" in the relevant scope. |
| $C_{ij} \approx 1$ | Reporter and partner have approximately the world-average alignment. |
| $C_{ij} < 1$ | Reporter's export pattern does not align with partner's import pattern. |

The Cij value is unitless; it is the product of three ratios. Movements in $C_{ij}$
through time reflect either (a) shifts in the reporter's export specialisation, or (b)
shifts in the partner's import specialisation, or (c) shifts in the world product mix
(captured by the $T/T_{k}$ factor) — these can be decomposed using the HS 4-digit and
HS 6-digit detail.

**What Cij does not measure.** $C_{ij}$ does not measure realised bilateral trade flows
between $i$ and $j$. Two economies can have a high $C_{ij}$ and yet trade little with
each other (because of preferential agreements with third parties, geographic distance,
or non-tariff barriers). The realised counterpart is the Trade Intensity Index ($T_{ij}$),
which uses bilateral trade values and is not computed in this study.

---

## 7. Output Tables

Three tables are produced per partner ($j$ = United States or China), all stored as
sheets in a single Excel workbook `{partner}_TCI.xlsx`:

| Sheet | Granularity | Key columns |
|---|---|---|
| Country Summary | Reporter $\times$ Year | Headline Cij (Drysdale-Garnaut, weighted), Headline Cij (RCA product, unweighted), count of active HS 6-digit pairs |
| HS4 Summary | Reporter $\times$ Year $\times$ HS 4-digit heading | $C_{ij,K}$ (DG), $C_{ij,K}^{\mathrm{Tan}}$, $\mathrm{RCA}_{x,i,K}$, $\mathrm{RCA}_{m,j,K}$, raw HS 4-digit totals, count of active HS 6-digit pairs |
| HS6 Detail | Reporter $\times$ Year $\times$ HS 6-digit code | $C_{ij,k}$ (DG), $C_{ij,k}^{\mathrm{Tan}}$, both RCAs, all underlying trade values, world share within HS 4-digit |

Time-series charts of HS 4-digit Cij by reporter are also exported as PNG files,
one per partner per HS 4-digit heading.

The headline always reports the full ICT-scope number; if a particular run filters
to a subset of HS 4-digit headings, that filter applies only to the HS4 and HS6 sheets.

---

## 8. Validation

Three checks support the integrity of the published results.

| # | What is verified | External benchmark | Threshold |
|---|---|---|---|
| 1 | The trade values stored in the project database match those published by UN Comtrade | UN Comtrade API | At least 93% of compared rows fall within 5% of the Comtrade value |
| 2 | The Balassa RCA scores at HS 6-digit match those published by World Bank WITS | WITS RCA dataset | Pearson correlation $r \ge 0.98$ |
| 3 | The two algebraically equivalent forms of Drysdale-Garnaut Cij at HS 6-digit produce identical numbers | Internal | Equality to floating-point precision |

Once checks 1 and 2 are satisfied, the HS 4-digit Cij and headline Cij outputs are
correct by arithmetic identity, since both are deterministic sums of validated HS 6-digit
inputs.

Detailed validation procedure and the latest results are recorded in
[`validation_methodology.md`](validation_methodology.md).

---

## 9. References

- Balassa, B., 1965. Trade Liberalisation and "Revealed" Comparative Advantage.
  *The Manchester School* 33(2): 99–123.
- Drysdale, P. and Garnaut, R., 1982. Trade Intensities and the Analysis of Bilateral
  Trade Flows in a Many-Country World: A Survey. *Hitotsubashi Journal of Economics*
  22(2): 62–84.
- Frankel, J., Stein, E. and Wei, S.-J., 1995. Trading Blocs and the Americas: The
  Natural, the Unnatural, and the Super-natural. *Journal of Development Economics*
  47(1): 61–95.
- Yang, L., 2023. Study on the Trade Complementarity among China and CEE Countries.
  *Academic Journal of Management and Social Sciences* 4(3).
- Fen, T., 2024. A Study on the Trade Complementarity and Competitiveness of
  Mechanical and Electric Products between China and RCEP Member Countries.
  *Proceedings of the 2023 International Conference on Management Innovation and
  Economy Development.*
- UNCTAD, 2024. Information and Communication Technology Goods Classification, HS 2022.

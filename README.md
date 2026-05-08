# Trade Complementarity Index — Indo-Pacific Reporters vs US and China

This project computes Drysdale-Garnaut Trade Complementarity Indices (Cij) for bilateral trade between Indo-Pacific reporter countries and the US and China, using HS 6-digit trade data from ITC Trade Map for 2001–2024. It is the empirical pipeline behind an academic paper on relative trade complementarity in the Indo-Pacific.

For developer / runtime instructions, see [`CLAUDE.md`](CLAUDE.md). For validation procedures and stage-by-stage methodology, see [`docs/validation_methodology.md`](docs/validation_methodology.md).

---

## Research Goal

Quantify, for each year 2001–2024:

- A single headline Cij per (reporter, partner) pair, summed over the UNCTAD Information and Communication Technology (ICT) goods scope (23 HS 4-digit headings, 107 HS 6-digit codes — see [Scope](#scope)).
- An HS 4-digit decomposition showing which ICT headings carry the complementarity (e.g. HS 8541 semiconductors, HS 8542 integrated circuits, HS 8471 computers).
- An HS 6-digit audit trail underneath both.

Reporters: Indo-Pacific (Australia, ASEAN-10, India, Japan, Korea, New Zealand, Taiwan).
Partners: United States and China, analysed one at a time.

---

## Formula Reference

### Drysdale-Garnaut (1982) — primary index

The bilateral Trade Complementarity Index for reporter $i$ and partner $j$, summed over commodities $k$:

$$
C_{ij} \;=\; \sum_{k}\, \frac{X_{i,k}}{X_{i}} \cdot \frac{T}{T_{k}} \cdot \frac{M_{j,k}}{M_{j}}
$$

| Symbol | Meaning |
|---|---|
| $X_{i,k}$ | Country $i$ exports of commodity $k$ to the world |
| $X_{i}$ | Country $i$ total exports to the world |
| $M_{j,k}$ | Country $j$ imports of commodity $k$ from the world |
| $M_{j}$ | Country $j$ total imports from the world |
| $T_{k}$ | World trade (exports) of commodity $k$ |
| $T$ | World total trade (exports) |

Interpretation: $C_{ij}$ measures the extent to which $i$'s export specialisation against the world matches $j$'s import specialisation against the world. $C_{ij} > 1$ indicates that $i$ and $j$ are "natural trading partners" in the sense of Frankel, Stein and Wei (1995).

### Balassa RCA at HS 6-digit

Each commodity $k$ has two Balassa Revealed Comparative Advantages:

$$
\mathrm{RCA}_{x,i,k} \;=\; \frac{X_{i,k}/X_{i}}{T_{k}/T} \qquad\quad
\mathrm{RCA}_{m,j,k} \;=\; \frac{M_{j,k}/M_{j}}{T_{k}/T}
$$

These two RCAs are reported alongside Cij in all output sheets.

### Drysdale-Garnaut, RCA-decomposition

The same Cij can be written as a product of the two RCAs and the world-trade share:

$$
C_{ij,k}^{\,\mathrm{DG}} \;=\; \mathrm{RCA}_{x,i,k} \cdot \mathrm{RCA}_{m,j,k} \cdot \frac{T_{k}}{T}
$$

Algebraically identical to the single-term DG above; included as an internal consistency check.

### Tan Fen (2024) variant — reported, not primary

$$
C_{k}^{\,\mathrm{Tan}} \;=\; \mathrm{RCA}_{x,i,k} \cdot \mathrm{RCA}_{m,j,k}
$$

Drops the world-trade-share factor $T_{k}/T$. Larger for niche products. Suited to product-by-product comparisons. **Not algebraically equivalent to Drysdale-Garnaut** — the two differ by a factor of $T/T_{k}$:

$$
C_{k}^{\,\mathrm{Tan}} \;=\; C_{ij,k}^{\,\mathrm{DG}} \cdot \frac{T}{T_{k}}
$$

> **Relationship to the Yang (2023) and Fen (2024) RCA-product form.** The Tan Fen single-product index $C_{k}^{\,\mathrm{Tan}} = \mathrm{RCA}_{x,i,k} \cdot \mathrm{RCA}_{m,j,k}$ is **not** algebraically equivalent to the Drysdale-Garnaut definition. Step-by-step derivation showing the $T/T_{k}$ factor difference is recorded in [`readings/formula.pdf`](readings/formula.pdf). The pipeline reports both forms; the Drysdale-Garnaut form is used as the primary index following the original 1982 definition, and the Tan Fen form is reported alongside for product-level comparisons.

---

## Pipeline — Three-Stage Architecture

All outputs are derived from a single HS 6-digit data source. Each tier is a deterministic transformation of the one below, so validation of HS 6-digit RCA propagates upward.

### Stage 1 — HS 6-digit RCA

Computed directly from World Trade Map values. Yields one $\mathrm{RCA}_{x,i,k}$ and one $\mathrm{RCA}_{m,j,k}$ per (reporter, partner, year, commodity).

By construction, RCA = 0 for any HS 6-digit line where the reporter has zero world exports of $k$, or where the partner has zero world imports of $k$. Such lines drop out of all subsequent aggregation without any explicit filter.

**External validation:** Pearson correlation against World Bank WITS published RCA, $r \ge 0.98$ (Korea and Japan, HS 8542, 2022).

### Stage 2 — HS 4-digit RCA

Aggregated from HS 6-digit RCA as a world-share weighted average:

$$
\mathrm{RCA}_{x,i,K} \;=\; \sum_{k \in K} \mathrm{RCA}_{x,i,k} \cdot \frac{T_{k}}{\sum_{k \in K} T_{k}}
$$

with $K$ = HS 4-digit heading. Same for the import RCA. The weight is each HS 6-digit code's share of world trade within its heading. This is **algebraically identical** to summing HS 6-digit trade values then applying the Balassa formula once at HS 4-digit level — both forms are documented in `docs/validation_methodology.md`.

**Validation by inheritance:** Stage 2 is a deterministic function of Stage 1, so no additional external check is required.

### Stage 3 — HS 4-digit Cij and headline Cij

Both outputs are computed by summing HS 6-digit Cij values over the appropriate scope. This preserves the bilateral-product-matching information that the HS 6-digit layer carries: an HS 6-digit term contributes to its parent heading only when both the reporter's world export and the partner's world import of that exact commodity are non-zero.

**HS 4-digit Cij** (one per reporter, partner, year, HS 4-digit heading $K$):

$$
C_{ij,K} \;=\; \sum_{k \in K} \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{T}{T_{k}}
$$

**Headline Cij** (one per reporter, partner, year):

$$
C_{ij} \;=\; \sum_{k \in \mathrm{scope}} \frac{X_{i,k}}{X_{i}} \cdot \frac{M_{j,k}}{M_{j}} \cdot \frac{T}{T_{k}}
$$

The headline sum runs over all HS 6-digit commodities in the analysis scope (the 23 HS 4-digit headings of the UNCTAD Information and Communication Technology classification, HS 2022 — see [Scope](#scope) below). HS 4-digit Cij is therefore a sub-aggregate of the headline. This is the Drysdale-Garnaut definition (eq. 2) applied at the heading level and at the country-pair level respectively.

> **Why HS 4-digit Cij is summed from HS 6-digit and not derived from HS 4-digit RCA.** Once HS 6-digit RCAs are collapsed into HS 4-digit RCAs, the HS 6-digit distribution is lost. Two scenarios that differ entirely at HS 6-digit level can produce identical HS 4-digit RCAs and therefore identical Cij under the product-of-RCAs form:
>
> | Scenario | Reporter exports | Partner imports | $\mathrm{RCA}_{x,K}$ | $\mathrm{RCA}_{m,K}$ | Cij from HS4 RCAs | Cij from sum of HS6 |
> |---|---|---|---|---|---|---|
> | Matched | 50 of 854231, 50 of 854232 | 50 of 854231, 50 of 854232 | 0.5 | 0.5 | 0.05 | 0.05 |
> | Mismatched | 100 of 854231, 0 of 854232 | 0 of 854231, 100 of 854232 | 0.5 | 0.5 | 0.05 | 0 |
>
> The product-of-RCAs form reports complementarity in both cases. The sum-of-HS6 form reports zero where there is no HS 6-digit overlap. Because Drysdale-Garnaut Cij is fundamentally about product-level alignment, this pipeline uses the sum-of-HS6 form. HS 4-digit RCAs are still exported as standalone heading-level specialisation metrics.

**Tan Fen variant at the HS 4-digit level**

$$
C_{K}^{\,\mathrm{Tan}} \;=\; \sum_{k \in K} \mathrm{RCA}_{x,i,k} \cdot \mathrm{RCA}_{m,j,k}
$$

Reported alongside the Drysdale-Garnaut form for sensitivity comparison; not used as the headline.

**Auxiliary HS 4-digit RCA values.** $\mathrm{RCA}_{x,i,K}$ and $\mathrm{RCA}_{m,j,K}$ from Stage 2 are exported as their own columns to describe heading-level specialisation. They are not used to compute HS 4-digit Cij.

---

## Output Files

All exports live in `data/TradeMapData/export/`.

| File | Sheet | Granularity | Primary columns |
|---|---|---|---|
| `{partner}_TCI.xlsx` | `Country Summary` | Reporter × Year | `Headline_Cij_Drysdale_Garnaut`, `Headline_Cij_Tan_Fen`, `Active_HS6_Pairs` |
| `{partner}_TCI.xlsx` | `HS4 Summary` | Reporter × Year × HS4 | `TCI_Drysdale_Garnaut` (sum of HS6), `TCI_Tan_Fen` (sum of HS6), `RCA_Reporter_Export`, `RCA_Partner_Import`, raw totals, `Active_HS6_Pairs` |
| `{partner}_TCI.xlsx` | `HS6 Detail` | Reporter × Year × HS6 | `TCI_Drysdale_Garnaut`, `TCI_RCA_DG_Decomposition` (cross-check), `TCI_Tan_Fen`, `RCA_Reporter_Export`, `RCA_Partner_Import`, `Proportion_World_Trade`, `World_Share_Within_HS4`, all raw flows |
| `{partner}_{HS4}_TCI_DG.png` | — | Time series | HS4 DG Cij per reporter |

The `hs4_codes` filter applies to the HS4 and HS6 sheets only — the `Country Summary` sheet always reports the full ICT-scope headline regardless of HS4 subset, so the headline number is comparable across runs.

### How to run

```bash
# Full ICT scope, all reporters, all years
conda run -n Econometrics_Deps python manage.py shell -c "from loadFiles.services.TCICalculator import TCICalculator; TCICalculator().run()"

# Filtered (HS4 and HS6 sheets only; headline still full scope)
conda run -n Econometrics_Deps python manage.py shell -c "from loadFiles.services.TCICalculator import TCICalculator; TCICalculator().run(countries=['Vietnam','KoreaRepublic'], hs4_codes=['8542','8541'])"

# Or via HTTP endpoint
conda run -n Econometrics_Deps python manage.py runserver
curl -X POST http://localhost:8000/loadFiles/calculate_tci
```

The database must be loaded first via `TradeMapLoader().load()` or the `GET /loadFiles/load_trade_data_to_db` endpoint.

---

## Validation

Three checks confirm the HS 6-digit calculation layer; see [`docs/validation_methodology.md`](docs/validation_methodology.md) for full methodology and results.

| # | What | Source | Threshold |
|---|---|---|---|
| 1 | DB trade values vs UN Comtrade | Comtrade API | ≥ 93% within 5% |
| 2 | HS 6-digit RCA vs World Bank WITS | WITS CSV | Pearson $r \ge 0.98$ |
| 3 | DG vs RCA-decomposition Cij at HS 6-digit | Internal | Exact equality |

If checks 1–3 pass, all downstream HS 4-digit and headline outputs are correct by arithmetic identity from the validated HS 6-digit inputs.

---

## Scope

The analysis is restricted to the 23 HS 4-digit headings of the UNCTAD Information and Communication Technology (ICT) goods classification under HS 2022. These headings cover 107 HS 6-digit codes (source: `readings/ICTList.docx`).

| HS4 | HS6 count | Description |
|---|---|---|
| 8443 | 2 | Printing machinery |
| 8470 | 5 | Calculating machines, data recording |
| 8471 | 8 | Automatic data-processing machines |
| 8472 | 1 | Office machines |
| 8473 | 3 | Parts and accessories |
| 8517 | 9 | Telephone sets, smartphones, network apparatus |
| 8518 | 8 | Microphones, loudspeakers |
| 8519 | 4 | Sound recording / reproducing apparatus |
| 8521 | 2 | Video recording / reproducing apparatus |
| 8522 | 2 | Parts for sound and video apparatus |
| 8523 | 5 | Discs, tapes, solid-state storage, smart cards |
| 8524 | 6 | Flat panel display modules |
| 8525 | 6 | Transmission apparatus for radio / TV |
| 8527 | 8 | Reception apparatus for radio-broadcasting |
| 8528 | 9 | Monitors, projectors |
| 8529 | 2 | Parts for displays and transmission apparatus |
| 8531 | 1 | Electric signalling apparatus |
| 8534 | 1 | Printed circuits |
| 8540 | 11 | Thermionic, cathode and photo-cathode tubes |
| 8541 | 6 | Semiconductor devices, photosensitive elements |
| 8542 | 5 | Electronic integrated circuits |
| 9013 | 1 | Lasers, optical appliances |
| 9504 | 2 | Video game consoles |

Pipeline filter: HS6 codes whose first four digits fall in this list. All other codes are excluded before Stage 1.

---

## What This Index Does and Does Not Measure

Cij measures **potential** bilateral complementarity — the alignment of reporter $i$'s export specialisation against the world with partner $j$'s import specialisation against the world.

It does **not** measure realised bilateral trade flows. A separate index such as the Trade Intensity Index would be required for that purpose.

---

## References

- Drysdale, P. and Garnaut, R., 1982. Trade intensities and the analysis of bilateral trade flows in a many-country world.
- Frankel, J., Stein, E. and Wei, S.-J., 1995. Trading blocs and the Americas: The natural, the unnatural, and the super-natural.
- Yang, L., 2023. Study on the Trade Complementarity among China and CEE Countries. *Academic Journal of Management and Social Sciences*, 4(3).
- Fen, T., 2024. A Study on the Trade Complementarity and Competitiveness of Mechanical and Electric Products between China and RCEP Member Countries. *Proceedings of the 2023 International Conference on Management Innovation and Economy Development.*
- Balassa, B., 1965. Trade liberalisation and "revealed" comparative advantage.

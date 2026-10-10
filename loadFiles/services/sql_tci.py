"""
SQL implementation of the TCI computation.

This module replaces the pandas "busy dataframe" pipeline (the old
`trade_data_loader._merge_for_partner` + `TCICalculator._calculate_*` /
`_aggregate_*` methods) with one readable SQL query per output structure, run
through the Django DB connection. `TCICalculator` orchestrates these and stores
the resulting DataFrames in the same `*_by_partner` dicts the exporters/tests
consume — the column contract is unchanged.

Design notes
------------
* Every value bound into the SQL (partner name, scope codes, year range) comes
  from trusted code constants — `Scope` objects and the fixed 2001–2024 window —
  never from user input, so they are inlined as literals. That keeps the SQL
  fully inspectable and sidesteps Django/SQLite's positional-only `%s` binding,
  which is brittle across the many sub-queries here.
* Divide-by-zero is handled with `COALESCE(num / NULLIF(den, 0), 0)`, the SQL
  twin of the old pandas `… / denom.replace(0, np.nan)` then `.fillna(0)`.
  A NULL in any factor of a product propagates to NULL → COALESCE 0, exactly
  like pandas `(a*b*c).fillna(0)`.
* `Year` is projected as TEXT so the output frames keep the string dtype the
  old loader produced (`df['Year'].astype(str)`).
* Restricted codes (8524 before 2022) are dropped in *every* product-level
  sub-query — numerator and all tier denominators — matching the loader's
  `_drop_restricted_codes`, so one code universe feeds everything.

Tables (Django default names for the `loadFiles` app; SQLite matches them
case-insensitively):
  loadFiles_countryexporttoworld   reporter, product_code, year, value_usd_thousands
  loadFiles_countryexporttopartner reporter, partner, product_code, year, value
  loadFiles_partnerimportfromworld partner, product_code, year, value
  loadFiles_worldexport            product_code, year, value
  loadFiles_hsproduct              product_code, product_label
  loadFiles_hssitcconcordance      product_code, hs_revision, sitc_section
"""

from __future__ import annotations

import pandas as pd

from loadFiles.services.scope import Scope

YEAR_MIN, YEAR_MAX = 2001, 2024

# Vacated/re-used HS codes: prefix → first valid year. Single-sourced here and
# rendered into a SQL guard; mirrors trade_data_loader.RESTRICTED_CODE_FIRST_VALID_YEAR.
RESTRICTED_CODE_FIRST_VALID_YEAR = {'8524': 2022}


# ── SQL fragment helpers ─────────────────────────────────────────────────────

def _sql_str(value: str) -> str:
    """Quote a string literal for SQL (escape embedded single quotes)."""
    return "'" + value.replace("'", "''") + "'"


def _restricted_guard(col: str = 'product_code') -> str:
    """`AND NOT (...)` dropping vacated/re-used codes before their valid year.
    Empty string if no restricted codes."""
    clauses = [
        f"({col} LIKE {_sql_str(prefix + '%')} AND year < {first_valid})"
        for prefix, first_valid in RESTRICTED_CODE_FIRST_VALID_YEAR.items()
    ]
    return f"AND NOT ({' OR '.join(clauses)})" if clauses else ""


def _year_guard() -> str:
    return f"AND year BETWEEN {YEAR_MIN} AND {YEAR_MAX}"


def _scope_filter(scope: Scope, col: str = 'product_code') -> str:
    """`AND SUBSTR(col,1,n) IN (...)` for the scope's HS-prefix filter.
    Empty string when the scope keeps the whole HS6 universe (Yang)."""
    if not scope.filter_codes:
        return ""
    codes = ", ".join(_sql_str(c) for c in scope.filter_codes)
    return f"AND SUBSTR({col}, 1, {scope.filter_digits}) IN ({codes})"


# Product-level row guards reused across queries.
def _product_row_guards() -> str:
    return f"product_code <> 'TOTAL' {_restricted_guard()} {_year_guard()}"


# ── HS6 indicator query ──────────────────────────────────────────────────────

def hs6_indicators_sql(scope: Scope, partner: str) -> str:
    """Per (reporter, year, HS6) for one partner: base trade values + every HS6
    indicator. Row universe = reporter-export-to-world rows (scope+year filtered)
    for reporters that trade with this partner — the old `_merge_for_partner`
    universe. Replaces _merge_for_partner + _calculate_tci_drysdale_garnaut +
    _calculate_rca_and_tci_rca."""
    p = _sql_str(partner)
    guards = _product_row_guards()
    scope_clause = _scope_filter(scope)
    return f"""
WITH
reporters AS (
    SELECT DISTINCT reporter FROM loadFiles_countryexporttopartner WHERE partner = {p}
),
rw AS (   -- reporter export to world (HS6 row universe, scope+year filtered)
    SELECT reporter, product_code, year, value_usd_thousands AS rew
    FROM loadFiles_countryexporttoworld
    WHERE {guards} {scope_clause}
      AND reporter IN (SELECT reporter FROM reporters)
),
bil AS (  -- reporter export to this partner (bilateral)
    SELECT reporter, product_code, year, value_usd_thousands AS rep
    FROM loadFiles_countryexporttopartner
    WHERE partner = {p} AND {guards}
),
pim AS (  -- partner imports from world, HS6
    SELECT product_code, year, value_usd_thousands AS mjk
    FROM loadFiles_partnerimportfromworld
    WHERE partner = {p} AND {guards}
),
we AS (   -- world exports, HS6
    SELECT product_code, year, value_usd_thousands AS wk
    FROM loadFiles_worldexport
    WHERE {guards}
),
whs4 AS ( -- world HS4 total (canonical denominator), reporter-independent
    SELECT SUBSTR(product_code,1,4) AS hs4, year, SUM(value_usd_thousands) AS whs4
    FROM loadFiles_worldexport
    WHERE {guards}
    GROUP BY SUBSTR(product_code,1,4), year
),
rtot AS ( SELECT reporter, year, value_usd_thousands AS xi
          FROM loadFiles_countryexporttoworld WHERE product_code = 'TOTAL' ),
ptot AS ( SELECT year, value_usd_thousands AS mj
          FROM loadFiles_partnerimportfromworld WHERE partner = {p} AND product_code = 'TOTAL' ),
wtot AS ( SELECT year, value_usd_thousands AS w
          FROM loadFiles_worldexport WHERE product_code = 'TOTAL' ),
labels AS ( SELECT product_code, product_label FROM loadFiles_hsproduct )
SELECT
    rw.reporter                                         AS "Country",
    CAST(rw.year AS TEXT)                               AS "Year",
    rw.product_code                                     AS "Product code",
    labels.product_label                                AS "Product label",
    COALESCE(bil.rep, 0)                                AS "Reporter Export To Partner",
    rw.rew                                              AS "Reporter Export To World",
    COALESCE(pim.mjk, 0)                                AS "Partner Import From World",
    we.wk                                               AS "World Export of item k",
    rtot.xi                                             AS "Reporter's Total Export To World",
    ptot.mj                                             AS "Partner's Total Import From World",
    wtot.w                                              AS "Total World Export",
    whs4.whs4                                           AS "World Export HS4 Total",
    -- TCI_Drysdale_Garnaut = (Xik/Xi)·(Mjk/Mj)·(W/Wk)
    COALESCE(
        (rw.rew / NULLIF(rtot.xi,0))
        * (COALESCE(pim.mjk,0) / NULLIF(ptot.mj,0))
        * (wtot.w / NULLIF(we.wk,0)), 0)                AS "TCI_Drysdale_Garnaut",
    -- RCA Reporter Export = (Xik/Xi) / (Wk/W)
    COALESCE(
        (rw.rew / NULLIF(rtot.xi,0))
        / NULLIF(we.wk / NULLIF(wtot.w,0), 0), 0)       AS "RCA Reporter Export",
    -- RCA Partner Import = (Mjk/Mj) / (Wk/W)
    COALESCE(
        (COALESCE(pim.mjk,0) / NULLIF(ptot.mj,0))
        / NULLIF(we.wk / NULLIF(wtot.w,0), 0), 0)       AS "RCA Partner Import",
    -- Proportion World Trade = Wk/W
    COALESCE(NULLIF(we.wk / NULLIF(wtot.w,0), 0), 0)    AS "Proportion World Trade",
    -- TCI_RCA_DG_Decomposition = RCA_x · RCA_m · (Wk/W)
    COALESCE(
        (rw.rew / NULLIF(rtot.xi,0)) / NULLIF(we.wk / NULLIF(wtot.w,0), 0)
        * (COALESCE(pim.mjk,0) / NULLIF(ptot.mj,0)) / NULLIF(we.wk / NULLIF(wtot.w,0), 0)
        * COALESCE(NULLIF(we.wk / NULLIF(wtot.w,0), 0), 0), 0)
                                                        AS "TCI_RCA_DG_Decomposition",
    CASE WHEN rw.rew > 0 AND COALESCE(pim.mjk,0) > 0 THEN 1 ELSE 0 END
                                                        AS "Active_Pair"
FROM rw
LEFT JOIN bil    ON bil.reporter = rw.reporter AND bil.product_code = rw.product_code AND bil.year = rw.year
LEFT JOIN pim    ON pim.product_code = rw.product_code AND pim.year = rw.year
LEFT JOIN we     ON we.product_code  = rw.product_code AND we.year  = rw.year
LEFT JOIN whs4   ON whs4.hs4 = SUBSTR(rw.product_code,1,4) AND whs4.year = rw.year
LEFT JOIN rtot   ON rtot.reporter = rw.reporter AND rtot.year = rw.year
LEFT JOIN ptot   ON ptot.year = rw.year
LEFT JOIN wtot   ON wtot.year = rw.year
LEFT JOIN labels ON labels.product_code = rw.product_code
ORDER BY rw.product_code ASC, rw.year DESC
"""


# ── tier index query (HS4 / HS2) ─────────────────────────────────────────────

def tier_index_sql(scope: Scope, partner: str, digits: int, suffix: str) -> str:
    """Per (reporter, year, tier) for one partner. Cij = Σ HS6 DG in tier
    (scope+year filtered numerator); RCAs from canonical totals (full code
    universe). Replaces _aggregate_hs6_to_hs4 / _aggregate_hs4_to_hs2.
    `digits` = 4 or 2, `suffix` = '4digit' or '2digit'."""
    p = _sql_str(partner)
    guards = _product_row_guards()
    scope_clause = _scope_filter(scope)
    tier = f"SUBSTR(product_code, 1, {digits})"
    tier_col = 'HS4' if digits == 4 else 'HS2'
    return f"""
WITH
reporters AS (
    SELECT DISTINCT reporter FROM loadFiles_countryexporttopartner WHERE partner = {p}
),
-- numerator: HS6 DG summed to the tier, over the scoped HS6 universe
hs6 AS (
    SELECT rw.reporter, rw.year, {tier.replace('product_code','rw.product_code')} AS tier,
           rw.rew, COALESCE(pim.mjk,0) AS mjk, we.wk,
           rtot.xi, ptot.mj, wtot.w
    FROM (
        SELECT reporter, product_code, year, value_usd_thousands AS rew
        FROM loadFiles_countryexporttoworld
        WHERE {guards} {scope_clause}
          AND reporter IN (SELECT reporter FROM reporters)
    ) rw
    LEFT JOIN ( SELECT product_code, year, value_usd_thousands AS mjk
                FROM loadFiles_partnerimportfromworld WHERE partner = {p} AND {guards} ) pim
           ON pim.product_code = rw.product_code AND pim.year = rw.year
    LEFT JOIN ( SELECT product_code, year, value_usd_thousands AS wk
                FROM loadFiles_worldexport WHERE {guards} ) we
           ON we.product_code = rw.product_code AND we.year = rw.year
    LEFT JOIN ( SELECT reporter, year, value_usd_thousands AS xi
                FROM loadFiles_countryexporttoworld WHERE product_code='TOTAL' ) rtot
           ON rtot.reporter = rw.reporter AND rtot.year = rw.year
    LEFT JOIN ( SELECT year, value_usd_thousands AS mj
                FROM loadFiles_partnerimportfromworld WHERE partner={p} AND product_code='TOTAL' ) ptot
           ON ptot.year = rw.year
    LEFT JOIN ( SELECT year, value_usd_thousands AS w
                FROM loadFiles_worldexport WHERE product_code='TOTAL' ) wtot
           ON wtot.year = rw.year
),
numer AS (
    SELECT reporter, year, tier,
           SUM( COALESCE(
                (rew / NULLIF(xi,0)) * (mjk / NULLIF(mj,0)) * (w / NULLIF(wk,0)), 0) ) AS tci_dg,
           SUM( CASE WHEN rew > 0 AND mjk > 0 THEN 1 ELSE 0 END )                      AS n_active
    FROM hs6 GROUP BY reporter, year, tier
),
-- canonical tier totals (full code universe, NOT scope filtered)
rep_tier AS (
    SELECT reporter, {tier} AS tier, year, SUM(value_usd_thousands) AS rep_total
    FROM loadFiles_countryexporttoworld WHERE {guards}
    GROUP BY reporter, {tier}, year
),
par_tier AS (
    SELECT {tier} AS tier, year, SUM(value_usd_thousands) AS par_total
    FROM loadFiles_partnerimportfromworld WHERE partner = {p} AND {guards}
    GROUP BY {tier}, year
),
wor_tier AS (
    SELECT {tier} AS tier, year, SUM(value_usd_thousands) AS wor_total
    FROM loadFiles_worldexport WHERE {guards}
    GROUP BY {tier}, year
),
rtot AS ( SELECT reporter, year, value_usd_thousands AS xi
          FROM loadFiles_countryexporttoworld WHERE product_code='TOTAL' ),
ptot AS ( SELECT year, value_usd_thousands AS mj
          FROM loadFiles_partnerimportfromworld WHERE partner={p} AND product_code='TOTAL' ),
wtot AS ( SELECT year, value_usd_thousands AS w
          FROM loadFiles_worldexport WHERE product_code='TOTAL' )
SELECT
    n.reporter                          AS "Country",
    CAST(n.year AS TEXT)                AS "Year",
    n.tier                              AS "{tier_col}",
    n.tci_dg                            AS "TCI_DG_{suffix}",
    -- weighted-average Cij = DG · (W / W_tier)
    COALESCE(n.tci_dg * wtot.w / NULLIF(wor_tier.wor_total,0), 0)
                                        AS "TCI_DG_WeightedAvg_{suffix}",
    -- RCA export = (ΣXk/Xi)/(W_tier/W); RCA import = (ΣMk/Mj)/(W_tier/W)
    COALESCE( (rep_tier.rep_total / NULLIF(rtot.xi,0))
              / NULLIF(wor_tier.wor_total / NULLIF(wtot.w,0), 0), 0)
                                        AS "RCA_Export_{suffix}",
    COALESCE( (par_tier.par_total / NULLIF(ptot.mj,0))
              / NULLIF(wor_tier.wor_total / NULLIF(wtot.w,0), 0), 0)
                                        AS "RCA_Import_{suffix}",
    -- RCA product
    COALESCE( (rep_tier.rep_total / NULLIF(rtot.xi,0))
              / NULLIF(wor_tier.wor_total / NULLIF(wtot.w,0), 0), 0)
    * COALESCE( (par_tier.par_total / NULLIF(ptot.mj,0))
              / NULLIF(wor_tier.wor_total / NULLIF(wtot.w,0), 0), 0)
                                        AS "TCI_RCA_Product_{suffix}",
    COALESCE(rep_tier.rep_total, 0)     AS "Total_Reporter_Export",
    COALESCE(par_tier.par_total, 0)     AS "Total_Partner_Import",
    wor_tier.wor_total                  AS "Total_World_Export_K",
    n.n_active                          AS "Num_Active_HS6_Pairs"
FROM numer n
LEFT JOIN rep_tier ON rep_tier.reporter = n.reporter AND rep_tier.tier = n.tier AND rep_tier.year = n.year
LEFT JOIN par_tier ON par_tier.tier = n.tier AND par_tier.year = n.year
LEFT JOIN wor_tier ON wor_tier.tier = n.tier AND wor_tier.year = n.year
LEFT JOIN rtot     ON rtot.reporter = n.reporter AND rtot.year = n.year
LEFT JOIN ptot     ON ptot.year = n.year
LEFT JOIN wtot     ON wtot.year = n.year
ORDER BY n.reporter, n.year, n.tier
"""


# ── headline query ───────────────────────────────────────────────────────────

def headline_sql(scope: Scope, partner: str) -> str:
    """Per (reporter, year) scope-level headline Cij. Replaces
    _calculate_headline_cij."""
    p = _sql_str(partner)
    guards = _product_row_guards()
    scope_clause = _scope_filter(scope)
    return f"""
WITH
reporters AS (
    SELECT DISTINCT reporter FROM loadFiles_countryexporttopartner WHERE partner = {p}
),
hs6 AS (
    SELECT rw.reporter, rw.year, rw.rew, COALESCE(pim.mjk,0) AS mjk, we.wk,
           rtot.xi, ptot.mj, wtot.w
    FROM (
        SELECT reporter, product_code, year, value_usd_thousands AS rew
        FROM loadFiles_countryexporttoworld
        WHERE {guards} {scope_clause}
          AND reporter IN (SELECT reporter FROM reporters)
    ) rw
    LEFT JOIN ( SELECT product_code, year, value_usd_thousands AS mjk
                FROM loadFiles_partnerimportfromworld WHERE partner={p} AND {guards} ) pim
           ON pim.product_code = rw.product_code AND pim.year = rw.year
    LEFT JOIN ( SELECT product_code, year, value_usd_thousands AS wk
                FROM loadFiles_worldexport WHERE {guards} ) we
           ON we.product_code = rw.product_code AND we.year = rw.year
    LEFT JOIN ( SELECT reporter, year, value_usd_thousands AS xi
                FROM loadFiles_countryexporttoworld WHERE product_code='TOTAL' ) rtot
           ON rtot.reporter = rw.reporter AND rtot.year = rw.year
    LEFT JOIN ( SELECT year, value_usd_thousands AS mj
                FROM loadFiles_partnerimportfromworld WHERE partner={p} AND product_code='TOTAL' ) ptot
           ON ptot.year = rw.year
    LEFT JOIN ( SELECT year, value_usd_thousands AS w
                FROM loadFiles_worldexport WHERE product_code='TOTAL' ) wtot
           ON wtot.year = rw.year
),
agg AS (
    SELECT reporter, year,
           SUM( COALESCE((rew/NULLIF(xi,0))*(mjk/NULLIF(mj,0))*(w/NULLIF(wk,0)),0) ) AS headline_dg,
           SUM(rew) AS x_scope, SUM(mjk) AS m_scope, SUM(wk) AS w_scope,
           MAX(xi) AS x_total, MAX(mj) AS m_total, MAX(w) AS w_total,
           SUM( CASE WHEN rew>0 AND mjk>0 THEN 1 ELSE 0 END ) AS n_active
    FROM hs6 GROUP BY reporter, year
)
SELECT
    reporter                AS "Country",
    CAST(year AS TEXT)      AS "Year",
    headline_dg             AS "Headline_Cij_DG",
    COALESCE(headline_dg * w_total / NULLIF(w_scope,0), 0) AS "Headline_Cij_DG_WeightedAvg",
    COALESCE(
        ( (x_scope/NULLIF(x_total,0)) / NULLIF(w_scope/NULLIF(w_total,0),0) )
      * ( (m_scope/NULLIF(m_total,0)) / NULLIF(w_scope/NULLIF(w_total,0),0) ), 0)
                            AS "Headline_Cij_RCA_Product",
    n_active                AS "Num_Active_HS6_Pairs"
FROM agg
ORDER BY reporter, year
"""


# ── SITC query (Yang scope) ──────────────────────────────────────────────────

def _hs_revision_case(year_col: str) -> str:
    """SQL CASE replicating trade_data_loader.hs_revision_for_year."""
    return (f"CASE WHEN {year_col} <= 2006 THEN '2002' "
            f"WHEN {year_col} <= 2011 THEN '2007' "
            f"WHEN {year_col} <= 2016 THEN '2012' "
            f"WHEN {year_col} <= 2021 THEN '2017' ELSE '2022' END")


def sitc_index_sql(scope: Scope, partner: str) -> str:
    """Per (reporter, year, SITC section). Vintage-aware HS6→SITC join.
    Replaces _aggregate_to_sitc. Rows with no concordance match are dropped
    (INNER join), matching _assign_sitc_section's dropna."""
    p = _sql_str(partner)
    guards = _product_row_guards()
    scope_clause = _scope_filter(scope)
    rev = _hs_revision_case
    return f"""
WITH
conc AS ( SELECT product_code, hs_revision, sitc_section FROM loadFiles_hssitcconcordance ),
reporters AS (
    SELECT DISTINCT reporter FROM loadFiles_countryexporttopartner WHERE partner = {p}
),
hs6 AS (
    SELECT rw.reporter, rw.year, c.sitc_section AS sitc,
           rw.rew, COALESCE(pim.mjk,0) AS mjk, we.wk, rtot.xi, ptot.mj, wtot.w
    FROM (
        SELECT reporter, product_code, year, value_usd_thousands AS rew
        FROM loadFiles_countryexporttoworld
        WHERE {guards} {scope_clause}
          AND reporter IN (SELECT reporter FROM reporters)
    ) rw
    JOIN conc c ON c.product_code = rw.product_code AND c.hs_revision = {rev('rw.year')}
    LEFT JOIN ( SELECT product_code, year, value_usd_thousands AS mjk
                FROM loadFiles_partnerimportfromworld WHERE partner={p} AND {guards} ) pim
           ON pim.product_code = rw.product_code AND pim.year = rw.year
    LEFT JOIN ( SELECT product_code, year, value_usd_thousands AS wk
                FROM loadFiles_worldexport WHERE {guards} ) we
           ON we.product_code = rw.product_code AND we.year = rw.year
    LEFT JOIN ( SELECT reporter, year, value_usd_thousands AS xi
                FROM loadFiles_countryexporttoworld WHERE product_code='TOTAL' ) rtot
           ON rtot.reporter = rw.reporter AND rtot.year = rw.year
    LEFT JOIN ( SELECT year, value_usd_thousands AS mj
                FROM loadFiles_partnerimportfromworld WHERE partner={p} AND product_code='TOTAL' ) ptot
           ON ptot.year = rw.year
    LEFT JOIN ( SELECT year, value_usd_thousands AS w
                FROM loadFiles_worldexport WHERE product_code='TOTAL' ) wtot
           ON wtot.year = rw.year
),
numer AS (
    SELECT reporter, year, sitc,
           SUM( COALESCE((rew/NULLIF(xi,0))*(mjk/NULLIF(mj,0))*(w/NULLIF(wk,0)),0) ) AS tci_dg,
           SUM( CASE WHEN rew>0 AND mjk>0 THEN 1 ELSE 0 END ) AS n_active
    FROM hs6 GROUP BY reporter, year, sitc
),
-- canonical SITC totals (full universe), vintage-aware
rep_sitc AS (
    SELECT s.reporter, c.sitc_section AS sitc, s.year, SUM(s.value_usd_thousands) AS rep_total
    FROM loadFiles_countryexporttoworld s
    JOIN conc c ON c.product_code = s.product_code AND c.hs_revision = {rev('s.year')}
    WHERE s.product_code <> 'TOTAL' {_restricted_guard('s.product_code')} AND s.year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
    GROUP BY s.reporter, c.sitc_section, s.year
),
par_sitc AS (
    SELECT c.sitc_section AS sitc, s.year, SUM(s.value_usd_thousands) AS par_total
    FROM loadFiles_partnerimportfromworld s
    JOIN conc c ON c.product_code = s.product_code AND c.hs_revision = {rev('s.year')}
    WHERE s.partner = {p} AND s.product_code <> 'TOTAL' {_restricted_guard('s.product_code')} AND s.year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
    GROUP BY c.sitc_section, s.year
),
wor_sitc AS (
    SELECT c.sitc_section AS sitc, s.year, SUM(s.value_usd_thousands) AS wor_total
    FROM loadFiles_worldexport s
    JOIN conc c ON c.product_code = s.product_code AND c.hs_revision = {rev('s.year')}
    WHERE s.product_code <> 'TOTAL' {_restricted_guard('s.product_code')} AND s.year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
    GROUP BY c.sitc_section, s.year
),
rtot AS ( SELECT reporter, year, value_usd_thousands AS xi
          FROM loadFiles_countryexporttoworld WHERE product_code='TOTAL' ),
ptot AS ( SELECT year, value_usd_thousands AS mj
          FROM loadFiles_partnerimportfromworld WHERE partner={p} AND product_code='TOTAL' ),
wtot AS ( SELECT year, value_usd_thousands AS w
          FROM loadFiles_worldexport WHERE product_code='TOTAL' )
SELECT
    n.reporter                AS "Country",
    CAST(n.year AS TEXT)      AS "Year",
    n.sitc                    AS "SITC",
    n.tci_dg                  AS "TCI_DG_sitc",
    COALESCE(n.tci_dg * wtot.w / NULLIF(wor_sitc.wor_total,0), 0) AS "TCI_DG_WeightedAvg_sitc",
    COALESCE( (rep_sitc.rep_total/NULLIF(rtot.xi,0)) / NULLIF(wor_sitc.wor_total/NULLIF(wtot.w,0),0), 0)
                              AS "RCA_Export_sitc",
    COALESCE( (par_sitc.par_total/NULLIF(ptot.mj,0)) / NULLIF(wor_sitc.wor_total/NULLIF(wtot.w,0),0), 0)
                              AS "RCA_Import_sitc",
    COALESCE( (rep_sitc.rep_total/NULLIF(rtot.xi,0)) / NULLIF(wor_sitc.wor_total/NULLIF(wtot.w,0),0), 0)
    * COALESCE( (par_sitc.par_total/NULLIF(ptot.mj,0)) / NULLIF(wor_sitc.wor_total/NULLIF(wtot.w,0),0), 0)
                              AS "TCI_RCA_Product_sitc",
    n.n_active                AS "Num_Active_HS6_Pairs"
FROM numer n
LEFT JOIN rep_sitc ON rep_sitc.reporter = n.reporter AND rep_sitc.sitc = n.sitc AND rep_sitc.year = n.year
LEFT JOIN par_sitc ON par_sitc.sitc = n.sitc AND par_sitc.year = n.year
LEFT JOIN wor_sitc ON wor_sitc.sitc = n.sitc AND wor_sitc.year = n.year
LEFT JOIN rtot     ON rtot.reporter = n.reporter AND rtot.year = n.year
LEFT JOIN ptot     ON ptot.year = n.year
LEFT JOIN wtot     ON wtot.year = n.year
ORDER BY n.reporter, n.year, n.sitc
"""


# ── runners ──────────────────────────────────────────────────────────────────

def _run(sql: str) -> pd.DataFrame:
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [c[0] for c in cursor.description]
        rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=columns)


def load_hs6_indicators(scope: Scope, partner: str) -> pd.DataFrame:
    return _run(hs6_indicators_sql(scope, partner))


def load_tier_index(scope: Scope, partner: str, digits: int, suffix: str) -> pd.DataFrame:
    return _run(tier_index_sql(scope, partner, digits, suffix))


def load_headline(scope: Scope, partner: str) -> pd.DataFrame:
    return _run(headline_sql(scope, partner))


def load_sitc_index(scope: Scope, partner: str) -> pd.DataFrame:
    from loadFiles.models import HSSITCConcordance
    if not HSSITCConcordance.objects.exists():
        return pd.DataFrame()  # mirror _aggregate_to_sitc early-return
    return _run(sitc_index_sql(scope, partner))

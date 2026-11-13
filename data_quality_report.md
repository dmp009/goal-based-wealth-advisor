# Data quality report

0 error(s), 2 warning(s).

| Severity | Check | Ticker | Detail |
|---|---|---|---|
| warning | stale_price | PE500.PA | 4 identical month-end closes (17.6516) from 2017-12-31 to 2018-03-31 |
| warning | stale_price | SP5C.PA | 4 identical month-end closes (169.01) from 2017-12-31 to 2018-03-31 |

## Checks run

| Check | Severity | What it detects |
|---|---|---|
| `price_gap` | error | more than one month between two consecutive prices of a ticker |
| `non_positive_price` | error | missing, zero or negative adjusted close |
| `stale_price` | warning | 3 or more consecutive identical month-end closes (stale or forward-filled) |
| `etf_without_prices` | error | ETF of the configured universe with no price rows |
| `pea_holding_not_eligible` | error | PEA holding whose product is not PEA-eligible |
| `livret_a_over_cap` | error | Livret A balance above the regulatory ceiling |

## Row counts

Client tables can be empty: the app reads the sample clients from `data/clients/`.

| Table | Rows |
|---|---|
| dim_product | 14 |
| fact_prices | 2736 |
| dim_client | 0 |
| fact_goals | 0 |
| fact_holdings | 0 |
| fact_proposals | 0 |
| fact_ai_documents | 0 |

## Proxy share per ticker

Months back-filled from a proxy index or ETF before the ETF's own history starts.

| Ticker | Months | Proxy months | Proxy share |
|---|---|---|---|
| AEEM.PA | 192 | 0 | 0.0% |
| AM3A.PA | 194 | 0 | 0.0% |
| CRP.PA | 211 | 0 | 0.0% |
| CW8.PA | 209 | 0 | 0.0% |
| DCAM.PA | 209 | 189 | 90.4% |
| ECRP.PA | 211 | 91 | 43.1% |
| ETZ.PA | 158 | 0 | 0.0% |
| MEUD.PA | 158 | 125 | 79.1% |
| MTD.PA | 214 | 0 | 0.0% |
| MTI.PA | 108 | 0 | 0.0% |
| PAEEM.PA | 192 | 101 | 52.6% |
| PCEU.PA | 158 | 67 | 42.4% |
| PE500.PA | 143 | 52 | 36.4% |
| SP5C.PA | 143 | 0 | 0.0% |
| ^STOXX50E | 236 | 0 | 0.0% |

# Methodology

Every rule, formula and parameter the engine uses, with its simplifications. Parameters live in
`config/*.yaml`; the code module is given for each step. "Today" is the last price date of the
snapshot (31 October 2026 in the committed data).

## 1. Suitability profile (`wealthadvisor/suitability/scoring.py`)

**Questionnaire** (`config/questionnaire.yaml`). Four sections, each scored as the sum of its
answer scores divided by the maximum possible (0 to 1):

| Section | Weight | Questions |
|---|--:|---|
| Knowledge and experience | 0.15 | Equity ETFs, bond ETFs, structured products (none / basic / experienced) |
| Financial situation | 0.25 | Loss capacity (low / medium / high), income stability |
| Objectives and horizon | 0.25 | Main objective (capital preservation to long-term growth), declared horizon |
| Risk tolerance | 0.35 | Reaction to a 20 % fall, return/risk trade-off, largest acceptable one-year loss |

`raw_score = 1 + 6 × Σ(weight × section score)`, a number between 1 and 7. The profile is
`1 + number of thresholds [1.5, 2.5, 3.5, 4.5, 5.5, 6.5] reached`, i.e. rounding half up.

**Cap rules**, applied in this order after the score. Each one that lowers the profile is
recorded in `rules_fired`; every applicable cap, binding or not, is recorded in `constraints`.

| Condition | Profile capped at |
|---|--:|
| Longest goal horizon < 3 years | 2 |
| Longest goal horizon 3 to 5 years | 3 |
| Loss capacity = low | 3 |
| No knowledge of equity ETFs | 4 |

Sample clients (exact profiles asserted by tests): Camille Laurent 3 (raw 4.05, capped by the
4.7-year horizon), Isabelle and Marc Moreau 4, Julien Deschamps 6, Monique Girard 2.

**Product-family checks** (`suitability/products.py`):

| Family | Rule |
|---|---|
| Livret A, fonds en euros | Capital-guaranteed, suitable for every profile |
| Bond ETFs | Allowed from profile 1 |
| Equity ETFs | Allowed from profile 2; profile 1 gets no equity |
| Structured products | Profile ≥ 4, horizon ≥ 8 years, declared knowledge of structured products |

When the client declares no knowledge of an allowed ETF family, an **appropriateness warning**
is added: the advisor must explain the risks before investing.

## 2. Risk profiles (`config/profiles.yaml`)

An in-house scale, **not** calibrated to the PRIIPs SRI bands.

| Profile | Volatility cap (bucket) | Max equity (bucket) | Min safe share |
|--:|--:|--:|--:|
| 1 | 2 % | 0 % | 80 % |
| 2 | 4 % | 20 % | 60 % |
| 3 | 7 % | 40 % | 40 % |
| 4 | 10 % | 60 % | 25 % |
| 5 | 13 % | 75 % | 10 % |
| 6 | 16 % | 90 % | 0 % |
| 7 | 20 % | 100 % | 0 % |

The safe share sits in Livret A or fonds en euros (volatility 0). The optimiser works on the
risky sleeve, so its caps are rescaled: sleeve volatility cap = cap ÷ (1 − safe share), sleeve
equity cap = min(1, max equity ÷ (1 − safe share)). This keeps the bucket's total equity
within the profile maximum.

## 3. Emergency fund and goal buckets (`wealthadvisor/wrappers/allocate.py`)

**Emergency fund.** 6 months of expenses for profiles 1-3, 3 months for profiles 4-7, capped at
the Livret A ceiling (22,950 €), held in Livret A and funded first from liquid assets. A
shortfall is reported. It is not topped up by the monthly saving.

**Buckets.** Each goal gets its own bucket.

- Target in today's euros, inflated at 2 % a year to the goal date
  (`target_nominal = target × 1.02^years`).
- Bucket risk = min(client profile, horizon cap): horizon < 3 years → 2, 3-5 years → 3,
  5-8 years → 4, ≥ 8 years → client profile.
- **Initial funding**: investable assets = liquid assets − funded emergency fund (debts are
  recorded but ignored). Essential goals first, then aspirational ones; inside each group, goals
  are funded one after the other by date (nearest first), each up to the present value of its
  target at the safe rate (Livret A rate under 3 years, fonds en euros rate otherwise). Any
  surplus goes to the longest-horizon bucket.
- **Monthly saving**: same order, each bucket capped by the level monthly annuity that closes
  its gap (target − funding grown at the safe rate); any leftover goes to the longest-horizon
  bucket.
- Funding goals one after the other rather than pro rata is a deliberate choice: it is how an
  advisor reasons ("secure the nearest essential goal first"), at the cost of far goals getting
  less when money is short.

## 4. Wrapper rules (`wrappers/allocate.py`)

Applied to each bucket's initial funding and to its monthly flow. Every rule that applies is
logged as a sentence in the bucket's `rules`.

1. **Safe sleeve**: horizon < 3 years → Livret A within the remaining ceiling, overflow to fonds
   en euros in the assurance-vie (AV); horizon ≥ 3 years → fonds en euros in AV.
2. **Equity**: horizon ≥ 5 years → PEA while cumulative contributions stay below 150,000 €,
   overflow to AV; 3-5 years → AV; < 3 years → CTO.
3. **Bonds in the risky sleeve**: AV when the horizon is ≥ 3 years, CTO otherwise.
4. **Shared caps**: the Livret A and PEA room is shared by all buckets and by monthly flows. A
   monthly flow is capped at remaining room ÷ months left, and the room is reduced by
   flow × months, so cumulative contributions respect both ceilings.
5. **PEA eligibility**: when a bucket uses the PEA, its equity universe is restricted to ETFs
   with `pea_eligible = true`. An unknown flag (null) counts as not eligible. Every equity class
   has at least one verified PEA-eligible ETF.
6. **Holdings**: equity euros go to the PEA up to the bucket's PEA amount, pro rata across the
   equity ETFs, overflow to AV (horizon ≥ 3 years) or CTO.

## 5. Simplified 2026 French tax (`wrappers/tax.py`, `config/tax_rules.yaml`)

| Wrapper | Rule on gains |
|---|---|
| PEA | Withdrawal before 5 years: 30 % (12.8 % + 17.2 %). From 5 years: 17.2 % social charges only |
| Assurance-vie (incl. fonds en euros) | Before 8 years: 30 %. From 8 years: 24.7 % (7.5 % + 17.2 %) after an allowance of 4,600 € (single) or 9,200 € (couple) |
| CTO | 30 % flat tax; cost basis = weighted average cost (*PRU*) |
| Livret A | Tax-free |

Simplifications: no income-tax option, no inheritance rules, no AV premiums above 150,000 €
rule, and the AV allowance is applied once to the gain taxed at the goal date (not per year of
withdrawals). The holding period is the bucket horizon.

## 6. Portfolio construction (`wealthadvisor/portfolio/`)

**One risk model for every method.**

- **Expected returns**: capital market assumptions (`config/capital_market_assumptions.yaml`),
  long-term nominal annual returns per asset class approximating J.P. Morgan Asset Management's
  2026 Long-Term Capital Market Assumptions (published October 2025): world equity 6.5 %,
  Europe 7.0 %, US 6.7 %, emerging 7.8 %, euro government bonds 3.0 %, euro corporate bonds
  3.7 %, euro inflation-linked 3.0 %. Only the emerging-market figure (USD basis) and the
  global equity order of magnitude could be checked against the press release; the file is
  marked `unverified: true` and lists the unconfirmed classes.
- **Covariance**: Ledoit-Wolf shrinkage on monthly returns over the common history window of
  all 14 ETFs (at least 36 months required), annualised × 12.
- **Proxy policy**: an ETF with a short history is back-filled with the returns of a
  longer-history ETF of the same asset class (e.g. DCAM.PA from CW8.PA, PE500.PA from SP5C.PA).
  The back-filled prices are anchored on the ETF's first own price and flagged `is_proxy`.
  MTI.PA (inflation-linked) has no proxy, which sets the common window (from December 2017).

**Methods** (risky sleeve, long only, weights below 0.01 % removed and renormalised):

- **Markowitz**: maximise expected return (CMA) subject to the sleeve volatility cap and the
  sleeve equity cap (`EfficientFrontier.efficient_risk`, PyPortfolioOpt). If the cap cannot be
  met, fall back to the minimum-volatility portfolio, and record a note.
- **Black-Litterman**: equilibrium returns π = δ Σ w_ref with δ = 2.5 and documented reference
  weights per asset class (world equity 30 %, Europe 10 %, US 10 %, EM 5 %, government bonds
  25 %, corporate 15 %, inflation-linked 5 %, split equally across the ETFs of each class
  present). Optional advisor views per asset class are blended with
  `BlackLittermanModel`. The posterior returns only **choose** the weights, which are then
  optimised under the same caps as Markowitz.
- **HRP** (implemented in-house on the shared covariance): correlation distance
  √((1 − ρ)/2), single linkage, quasi-diagonal leaf order, recursive bisection with
  inverse-variance cluster weights. The caps are then enforced: excess equity is moved to the
  lowest-volatility non-equity ETF, then weight is moved from the most volatile assets to the
  least volatile one (bisection on the amount) until the sleeve volatility is within its cap.
- **Evaluation**: all three portfolios are evaluated with the same CMA returns and covariance
  (expected return, volatility) plus the historical maximum drawdown of the sleeve over the
  common window. Bucket statistics combine the sleeve with the safe share at its rate.
- **Default choice**: HRP for buckets of risk ≤ 3 (more stable for cautious profiles),
  Black-Litterman otherwise. The advisor can switch per goal in the app.

## 7. Goal Monte Carlo (`wealthadvisor/goals/montecarlo.py`)

- 10,000 paths, monthly steps up to the goal date, fixed seed 42.
- Risky sleeve with fixed weights: its monthly return is normal with mean w·μ_m and variance
  w′Σ_m w, where μ_m = (1 + μ)^(1/12) − 1 and Σ_m = Σ / 12. Drawing this scalar is equivalent to
  drawing the full multivariate normal vector and projecting it.
- Safe sleeve: deterministic at the fonds en euros rate (2.5 %), or the Livret A rate (1.7 %)
  when the bucket's safe money is entirely in Livret A.
- Contributions arrive at month end with the bucket's safe/risky split.
- At the goal date, tax is applied to the total gain (final value − contributions), spread
  across wrappers pro rata to the bucket's realised wrapper amounts.
- **Probability** = share of paths whose after-tax value ≥ nominal target. P10 / P50 / P90 are
  after-tax percentiles; the fan chart shows pre-tax value percentiles over time.
- A goal is flagged *at risk* (`shortfall_flag`) when the displayed probability is below 50 %.

## 8. Structured products (`wealthadvisor/structured/payoff.py`, `config/structured.yaml`)

Generic templates on the Euro Stoxx 50, **not real issuer products**:

- **Autocall** (`autocall_sx5e`): 8 years, annual observations. If the index is at or above
  100 % of its initial level on an observation date, the product is called and pays 7 % per
  elapsed year. If never called, capital is repaid at maturity **unless the index has fallen
  more than 40 %** (barrier 60 %), in which case the investor bears the full index loss. This
  is conditional protection and is never described as "capital protected". Issuer credit risk
  applies.
- **Capital-protected note** (`cpn_sx5e`): 8 years, 100 % of capital at maturity plus 50 % of
  any rise of the index (price index, dividends excluded). Issuer credit risk applies.

**Simulation**: annual geometric Brownian motion on the index, 10,000 paths, seed 42. Drift =
CMA Europe equity return (7.0 %) − dividend yield (3.0 %), because the Euro Stoxx 50 is a price
index. Volatility = annualised standard deviation of the index's monthly returns in the
snapshot. Outputs: payoff distribution, probability of capital loss, and
annualised expected return = E[multiple]^(1 / E[life]) − 1.

**Eligibility and sizing**: the family check of §1 on the longest goal horizon; autocall for
profile ≥ 5, capital-protected note for profile 4; amount = 15 % of investable assets after the
emergency fund, carved from the longest-horizon bucket's risky sleeve before the ETFs are
optimised; held as a unit-linked product inside the assurance-vie if the client uses one,
otherwise in the CTO. Simplification: that bucket's Monte Carlo still models its whole risky
sleeve with the ETF weights.

## 9. Annual review (`wealthadvisor/review/engine.py`)

- **Proposal date**: the client's `proposal_date` (30 April 2025 for both sample reviews).
- **Derived holdings**: each product amount of the original proposal is bought at the last
  month-end price on or before the proposal date. At each later month end, Livret A and fonds
  en euros accrue one month of interest at the current configured rates, then the monthly
  saving is invested in the original wrapper/product proportions (Livret A only while below
  its ceiling, the rest to fonds en euros). Structured notes are held **at par** (no
  mark-to-market) and take no new money. `avg_cost` is the weighted average cost.
- **Performance**: monthly chain-linked time-weighted return per wrapper and in total;
  contributions arrive after the month's valuation, so they never count as return. Gain =
  value − total contributed.
- **Drift**: target = asset-class weights of the original proposal (fonds en euros and Livret A
  = "safe", structured = "structured"); current = derived holdings today. A class is rebalanced
  when |current − target| > 5 points (`drift_band` in `settings.yaml`). Structured notes are
  never rebalanced.
- **Trades**: money never moves between wrappers (future contributions do that). Inside each
  wrapper, over-weight flagged classes are sold and under-weight flagged classes bought toward
  the wrapper's original mix; buys equal sells per wrapper; a class trades its largest holding
  first. Livret A and structured notes are not traded. Trades under 0.50 € are dropped. CTO
  sales are taxable (30 % of the gain at the weighted average cost); PEA and AV sales are not
  taxable events.
- **Re-profiling**: the questionnaire is re-scored at the proposal date and today, with
  optional edited answers; a change of profile is flagged.
- **Goals before and now**: *before* re-runs the proposal engine at the proposal date (prices
  limited to that date) with the amount actually invested. *Now* re-simulates the same buckets
  (risk, safe share, chosen weights, monthly contribution, nominal target) from today's value:
  the portfolio minus the emergency fund is split across buckets pro rata to
  funding + months elapsed × monthly contribution, and horizons are measured from today.
  Simplification: the simulation uses the plan's ETF weights, not the ETFs actually held.
- A goal that the original plan left unfunded stays at 0 % before and now. Julien Deschamps'
  holiday home is kept that way on purpose, as the example of a gap the review must surface,
  and the review letter must say so.

## 10. AI documents and numeric verification (`wealthadvisor/ai/`)

**Generation.** Four document types (proposal and review, advisor summary and client
letter), each in English and French. The LLM (model set in `settings.yaml`) receives the
prompt template (`ai/prompts/*_v1.md`) and the facts JSON only, and must answer through a
forced `write_document` tool call (`title`, `body`). The prompt forbids any figure or
recommendation not in the facts, requires each goal to have its own section under a heading
that quotes its label (`label` in English, `label_fr` in French), forbids describing the
autocall as capital protected, and ends every document with the disclaimer, which the code
adds if it is missing.

**Facts naming.** Numeric values in the facts are only under keys ending in `_pct` (percent,
one decimal), `_eur` (whole euros), `_year` (4-digit year), `_count` (integer) or `age`. Numbers
written inside text fields of the facts (rules, reasons) are also allowed when cited with the
same unit.

**Numeric-check policy** (`ai/numbers.py`):

| Token | Must match |
|---|---|
| Percentage | A `_pct` fact within the written precision: ±0.5 point if written as an integer, ±0.05 at one decimal |
| Euro amount | A `_eur` fact within ±1 % (minimum 1 €); a zero fact only matches 0 |
| Year | A `_year` fact exactly |
| Age | The client's age exactly, when the context says it is an age ("52-year-old", "aged", "âge", "vous avez") |
| Duration (years, months, *ans*, *mois*) | A fact whose key ends in `_years_count` or `_months_count`, or a duration written in the facts' text, exactly |
| Plain number | Any numeric fact in scope |

- English and French formats are normalised (`1,234.5`, `1 234,5`, `1.234.567`), as are
  multipliers (`k`, `M`, *milliers*, *centaines*, *mille*) and basis points.
- **Fail closed**: every run of digits that is not a recognised number token must appear
  verbatim in a text field of the facts (an ISIN or a ticker); otherwise it is an error.
- **Signs**: an explicit minus must match a negative fact; an explicit plus a positive one.
- "About" / "environ" does not relax any tolerance.
- **Goal scoping**: a Markdown heading that names exactly one goal (label or goal id) scopes the
  lines under it until a heading of the same or higher level. A line that names exactly one
  goal label is scoped to it too. In scope, only that goal's numbers plus the client-level
  numbers are accepted.
- **Retry and failure**: one retry with the list of mismatches; then a hard failure. The
  document is not cached and the errors are shown. Only verified documents are cached.
- **Cache key**: SHA-256 of the facts JSON, the prompt version, the document type, the language
  and the prompt template text.

**Residual limits.**

- The checker verifies numbers, not meaning: a correct figure attached to the wrong statement
  within the same scope passes.
- A goal described without its label or id, or two goals named in one sentence, is checked
  against all numbers.
- In body text, only a verbatim goal label scopes a line; a goal id (often an ordinary word such
  as "retirement") scopes headings only.
- Plain numbers without a unit match any numeric fact in scope; numbers one to ten written as
  words and ordinal list markers are not checked.
- "No recommendation beyond the facts" is a prompt instruction, not a coded check.

The advisor reviews every document before it is sent; the checker removes the most damaging
error (an invented or misplaced figure), not the need for that review.

**Current state.** No document is committed: generation needs `ANTHROPIC_API_KEY` and
`python -m wealthadvisor.pipeline ai --refresh`. Until then the app shows "Not generated yet".

## 11. Data quality (`wealthadvisor/data/quality.py`)

Run at the end of every ingest; the result is written to `data_quality_report.md` (latest:
no issues).

| Check | Severity |
|---|---|
| Gap of more than one month inside a ticker's own history | error |
| Missing or non-positive adjusted close | error |
| ETF in `config/etfs.yaml` without any price | error |
| PEA holding in a product whose `pea_eligible` is not TRUE (null counts as not eligible) | error |
| Livret A balance above the ceiling | error |

## 12. Design choices that shape the outputs

| Choice | Effect |
|---|---|
| Sleeve equity cap = min(1, max equity ÷ (1 − safe share)) | Bucket equity never exceeds the profile maximum |
| Unknown PEA flag = not eligible; SRI unknown = not used | Fewer PEA candidates, never an ineligible PEA holding |
| Goals funded one after the other by date within each priority group | Nearest essential goals are secured first; far goals get less when money is short |
| PEA-only equity universe when a bucket uses the PEA | One optimisation per bucket, always legal in the PEA |
| *At risk* flag = displayed probability < 50 % | The flag agrees with what the advisor sees |
| Sample-client data tuned for a realistic spread of probabilities | The demo shows comfortable, borderline and at-risk goals |
| Goal labels in EN and FR; headings must quote them | Makes goal scoping of the checker possible in both languages |
| Unfunded goal kept at 0 % in the review | The review surfaces the gap instead of hiding it |
| AI cache shipped empty | No invented text in the repo; generation is an explicit user step |

## 13. Limitations

- Simplified 2026 French tax rules (see §5); no income-tax option or inheritance treatment.
- The four clients are fictional.
- Expected returns come from one published CMA, approximated and not fully verified; the goal
  probabilities depend heavily on them.
- Livret A (1.7 %) and fonds en euros (2.5 %) rates are those in `config/rates.yaml`, held
  constant over every horizon and over the whole review period.
- ETF SRI is unavailable (null) for every ETF; some PEA flags are unknown and treated as not
  eligible.
- Normal monthly returns understate tail risk and ignore fat tails and volatility clustering.
- Structured products are generic templates, simulated with a simple GBM, and valued at par in
  the review.
- AI documents are not generated until the pipeline runs with an API key.
- The numeric checker has the residual limits listed in §10.
- The client tables of the warehouse are not populated in the committed snapshot.

# Goal-Based Wealth Advisor — Design

Date: 2026-11-13 · Status: draft for review · Portfolio project 2 of 6
(see `../PORTFOLIO_PLAN.md` one level above the repo for the portfolio context)

## 1. Intent and why

**What it is.** A working tool for a **bank wealth advisor** (*conseiller en gestion de
patrimoine* at a French retail or private bank). The advisor uses it to (1) onboard a new
client — MiFID II suitability profile, *bilan patrimonial*, goal-based proposal across
French tax wrappers — and (2) run the **annual review** of an existing client — performance,
drift, re-profiling, goal probabilities, rebalancing. An LLM drafts the advisor summary and the
client letter **in English and French**, strictly from numbers the engine computed.

**Who it is for.** The advisor is the only user. The client never touches the app; the
advisor reviews every AI-drafted document before it is sent.

**Why.** Portfolio piece for an M2 internship (*stage*) in France. Targets: wealth
management / private banking support roles and DAIS roles (Data Analyst, Business Analyst,
Assistant PO, Data Consultant). It must show: real wealth-management judgement (suitability,
French wrappers, product rules), quantitative skill (portfolio optimisation, Monte Carlo,
structured-product payoffs), BI deployment, data governance, and responsible AI.

**Success looks like.** A recruiter opens the live Streamlit link, picks a sample client, and
in under two minutes sees a profile, a proposal with goal probabilities, an annual review with
concrete rebalancing trades, and a bilingual client letter — and the README explains the
business problem before the technology.

## 2. Goals, non-goals, anti-goals

**Goals**
- Two advisor workflows sharing one engine: **New client** and **Annual review**.
- MiFID II-style questionnaire → risk profile 1–7 with a written, traceable rationale.
- Proposal across **Livret A, PEA, assurance-vie (fonds en euros + unit-linked ETFs), CTO**,
  plus **structured products** only when suitable.
- Three portfolio construction methods compared side by side: **Markowitz (mean-variance),
  Black-Litterman, HRP**.
- Monte Carlo probability of reaching each client goal, with contributions over time.
- Bilingual (EN/FR) AI documents with a numeric consistency check.
- Same DAIS layer and engineering hygiene as project 1.

**Non-goals**
- Not a tax simulator: French tax rules are simplified, explicit and documented.
- No real client data, no authentication, no persistence of user edits beyond the session.
- No real bank products: structured products are generic templates; ETFs are real listed
  UCITS funds used only as market data.
- No API backend (option B was rejected), no Power BI in this project (planned for project 4).

**Anti-goals (would make it a failure even if it runs)**
- The AI invents or alters any figure, or gives advice the engine did not compute.
- A product is proposed to a client who fails its suitability rule, or an exclusion is not
  explained.
- The tool looks like real investment advice: every page and document carries
  "Educational project — not investment advice".

## 3. Constraints

- **Language:** the whole app UI, code, comments and docs in **English**. AI documents are
  produced in **English and French**. README ends with a "Résumé en français".
- **Runs without paid keys:** AI outputs for the sample clients are cached and committed;
  the LLM is called only with `--refresh` and `ANTHROPIC_API_KEY` (same pattern as project 1).
- **Free data only:** prices from yfinance; rates and rules from config files with sources noted.
- **Deployable on Streamlit Community Cloud:** the app reads only committed files (snapshot
  parquet, sample clients, AI cache) — no network at runtime.
- Python ≥ 3.11; tests and CI make no network calls.

## 4. Approaches considered

| | Approach | Trade-off | Decision |
|---|---|---|---|
| **A** | Same pattern as project 1: Python package + DuckDB + Streamlit app + PDF exports, new repo | Fastest, reuses proven structure (CI, snapshot, AI cache, deploy); architecture similar to project 1 | **Chosen by the user** |
| B | Engine behind a FastAPI service + separate front end | Looks more "production"; ~2× work; Streamlit Cloud can't host the API, so no free live demo | Rejected |
| C | A + Power BI dashboard of the advisor's client book | Shows DAX, but recruiters can't open a `.pbix`; Power BI already planned for project 4 | Deferred (possible extra later) |

**Library call (mine):** PyPortfolioOpt for Markowitz, Black-Litterman and HRP (standard,
tested). Everything advisor-specific is written in this repo: questionnaire scoring,
suitability rules, wrapper allocation, tax rules, structured products, goal Monte Carlo,
annual review, AI reports.

## 5. The two workflows (what the advisor sees)

App pages (English): **New client**, **Annual review**, **Product universe**, **Data quality**,
**About**. Sidebar: pick a sample client (or start blank on New client).

```
New client                                   Annual review
──────────                                   ─────────────
1 Client situation (age, income, expenses,   1 Load client (current holdings per wrapper,
  assets, debts, horizon, goals)               original proposal, contributions so far)
2 MiFID questionnaire → profile 1–7          2 Performance since start (per wrapper, total)
  + rationale + knowledge/experience          3 Drift vs target allocation (table + chart)
3 Wrapper plan (how much in Livret A, PEA,   4 Re-profile: questionnaire re-run, change flagged
  assurance-vie, CTO, structured)            5 Goal probabilities now vs at proposal
4 Portfolio per wrapper: Markowitz / BL /    6 Rebalancing trades (sell X € of A, buy Y € of B,
  HRP side by side; advisor picks one          per wrapper; CTO sales flagged as taxable)
5 Goal probabilities (Monte Carlo fan chart) 7 AI review letter EN/FR + advisor summary
6 Structured product: included or excluded   8 Export PDF
  with the reason
7 AI proposal: advisor summary + client
  letter, EN and FR
8 Export PDF (EN or FR)
```

## 6. Components

### 6.1 Product universe and parameters (`config/`)
- `etfs.yaml`: 12–15 real UCITS ETFs listed on Euronext Paris (Amundi, iShares, BNP Paribas
  Easy). Fields: ticker (yfinance), ISIN, name, asset class (`equity_world`, `equity_europe`,
  `equity_us`, `equity_em`, `bond_gov_euro`, `bond_corp_euro`, `bond_inflation`, …), PEA
  eligible (bool), SRI (1–7), TER. ISINs, PEA eligibility and SRI must be checked against the
  issuers' factsheets; any value not verified is marked `unverified: true` and documented.
- `rates.yaml`: fonds en euros net rate (default 2.5 %/yr), Livret A rate and cap (22,950 €),
  each with `source` and `as_of`.
- `tax_rules.yaml`: simplified rules (§6.6).
- `structured.yaml`: product templates (§6.8).
- `capital_market_assumptions.yaml`: long-term expected annual return per asset class, with
  source and date (e.g. a published bank/asset-manager CMA), used by Markowitz and as BL
  priors where relevant.
- `profiles.yaml`: risk profile 1–7 → target volatility band, max equity share, allowed
  products.

### 6.2 Data and governance (`wealthadvisor/data/`)
- Ingest monthly adjusted closes (≈10 years where available) for the ETF universe and the
  Euro Stoxx 50 index (`^STOXX50E`, for structured products) from yfinance; raw responses
  saved with timestamps (lineage).
- DuckDB star schema: `dim_product`, `dim_client`, `fact_prices`, `fact_holdings`,
  `fact_goals`, `fact_proposals`, `fact_ai_documents`.
- pandera checks: no gaps > 1 month, no non-positive prices, every ETF in config has prices,
  holdings reference known products, PEA holdings only PEA-eligible, Livret A ≤ cap.
  Report → `data_quality_report.md`.
- Committed parquet snapshot for the app (same as project 1).

### 6.3 Sample clients (`data/clients/`)
4 fictional clients as JSON, covering the space:
1. Young professional, 28, saving for a flat deposit in 5 years (profile ≈ 3).
2. Couple, 52, retirement in 2040, existing assurance-vie (profile ≈ 4).
3. Business owner, 45, high income, long horizon, structured-product experience (profile ≈ 5–6,
   structured product eligible).
4. Retiree, 68, income and capital preservation (profile ≈ 2; structured product excluded with reason).
Clients 2 and 3 also have **existing holdings** (≈1–2 years old) so the Annual review works
on them.

### 6.4 MiFID questionnaire and suitability (`wealthadvisor/suitability/`)
- Sections: knowledge & experience (per product family incl. structured products), financial
  situation (income, assets, loss capacity), objectives & horizon, risk tolerance.
- Deterministic scoring → profile 1–7; rules that cap the profile (e.g. short horizon or low
  loss capacity caps it regardless of tolerance). Every rule that fired is recorded as text:
  that list *is* the rationale shown to the advisor and fed to the AI.
- Suitability check for each product: allowed by profile, horizon, knowledge — returns
  included/excluded + reason.

### 6.5 Portfolio construction (`wealthadvisor/portfolio/`)
- Covariance: Ledoit-Wolf shrinkage on monthly returns.
- **Markowitz:** maximise expected return subject to the profile's volatility cap, using CMA
  returns.
- **Black-Litterman:** market-implied equilibrium returns (from a fixed reference weighting
  per asset class, documented) + optional advisor views (e.g. "Europe equity +1 %").
- **HRP:** covariance only.
- Constraints per wrapper: PEA → PEA-eligible ETFs only; weight bounds per asset class from the
  profile. Output for each method: weights, expected return, volatility, max historical
  drawdown. The advisor selects one method; default = HRP for profiles ≤ 3, BL otherwise
  (my call: HRP is more stable for cautious profiles; BL is the industry reference).

### 6.6 Wrapper allocation and simplified tax (`wealthadvisor/wrappers/`)
Ordered rules, each recorded as text for the rationale:
1. Emergency fund: 3–6 months of expenses in Livret A (up to the cap).
2. Short goals (< 5 years): fonds en euros / bond ETFs inside assurance-vie or Livret A.
3. Long-term equity: PEA first (up to 150,000 € contributions), with PEA-eligible ETFs.
4. Assurance-vie for the rest of the medium/long-term money: fonds en euros share by profile
   + unit-linked ETFs.
5. CTO only for what does not fit (non-PEA equity beyond AV needs, structured products if not
   held in AV).
Tax (simplified, documented as such): PEA — gains taxed only at social charges (17.2 %) after
5 years; assurance-vie — reduced taxation after 8 years; CTO — flat tax 30 %; Livret A tax-free.
Used to compute after-tax goal outcomes and to flag taxable sales in rebalancing.

### 6.7 Goal Monte Carlo (`wealthadvisor/goals/`)
- Monthly simulation, 10,000 paths, multivariate normal monthly returns from the covariance and
  expected returns of the chosen portfolio; fonds en euros and Livret A deterministic.
- Monthly contributions and planned withdrawals per goal; after-tax value at goal date.
- Output per goal: probability of reaching target, median and 10th/90th percentile outcomes;
  fan chart. Fixed random seed for reproducibility.

### 6.8 Structured products (`wealthadvisor/structured/`)
- Templates (generic, not real products):
  - **Autocall Euro Stoxx 50** (8 years, annual observations, autocall + coupon if index ≥
    100 % of initial, capital protected at maturity unless index < 60 % of initial).
  - **Capital-protected note** (100 % capital at maturity, participation in index upside).
- Payoff simulated by Monte Carlo on the index (GBM, volatility from history, drift from CMA),
  showing the distribution of outcomes and probability of capital loss.
- Eligibility (my proposed rule, configurable): profile ≥ 4, horizon ≥ 8 years, knowledge
  declared in the questionnaire, allocation ≤ 15 % of investable assets. If excluded, the
  reason is shown and included in the AI documents.

### 6.9 Annual review (`wealthadvisor/review/`)
- Performance since proposal per wrapper and total (time-weighted, contributions handled).
- Drift: current vs target weights; rebalance when an asset class drifts beyond a band
  (default ±5 points, configurable).
- Re-profile: questionnaire re-run with updated answers; profile change flagged.
- Goal probabilities now vs at proposal.
- Rebalancing trades in euros per wrapper, preferring moves inside PEA/assurance-vie (no tax)
  over CTO sales; CTO sales flagged with the estimated tax.

### 6.10 AI documents (`wealthadvisor/ai/`)
- Four document types: proposal advisor summary, proposal client letter, review advisor
  summary, review client letter — each in **EN and FR**.
- Input to the LLM: a JSON "facts" object built by the engine (profile + rationale, wrapper
  plan, weights, probabilities, exclusions with reasons, trades). The prompt forbids any number
  not in the facts and any recommendation not in the facts.
- **Numeric consistency check:** every number in the generated text (percentages, euro
  amounts, years) must match a value in the facts (with tolerance for rounding); otherwise the
  document is rejected and the failure shown to the advisor.
- Provider-agnostic client, Claude by default (model in config), tool-forced structured output,
  results cached in `data/ai_cache/` and committed for the sample clients.

### 6.11 Outputs and app (`app/`)
- Streamlit app, English UI, pages as in §5, reads only committed files.
- PDF export (proposal and review) in EN or FR: client letter + key tables + charts + disclaimer.

## 7. DAIS layer and engineering
Same as project 1: `docs/business_requirements.md` (advisor and compliance stakeholders,
user stories with acceptance criteria, KPI definitions), `docs/data_dictionary.md`,
`docs/data_model.md` (Mermaid), `docs/methodology.md` (every rule and formula, simplifications
and limitations), pytest with no network, ruff, GitHub Actions CI, README for recruiters
(business problem → demo → results → how it works → AI guardrails → governance → quickstart →
limitations → Résumé en français).

## 8. Delivery order
1. **Phase 1 – New client** end to end (data, suitability, portfolio, wrappers, goals,
   structured, AI, app page, PDF). Publishable on its own.
2. **Phase 2 – Annual review** on the same engine.
3. Docs, README, deploy.

## 9. Decisions settled after the builder check (designer's calls)

These answer the open questions a builder raised. They are the designer's calls, not the
user's, and are listed for review.

**9.1 One source of truth for risk and return.**
- Expected returns: `capital_market_assumptions.yaml` (long-term nominal annual return per
  asset class, from one published 2025/2026 long-term CMA, cited with date).
- Covariance: Ledoit-Wolf on monthly returns over the common history window.
- ETFs with less than 10 years of history are back-filled with a longer-history **proxy** of
  the same asset class (mapping in `etfs.yaml`, documented).
- Markowitz uses the CMA returns. Black-Litterman uses equilibrium returns from documented
  reference weights plus optional advisor views; it is used only to choose weights.
- **All three resulting portfolios are evaluated with the same CMA returns and covariance**
  (expected return, volatility, Monte Carlo). That keeps the comparison and the goal
  probabilities comparable.
- Fonds en euros and Livret A are risk-free assets with volatility 0 at their configured rates.
- Structured-product GBM: drift = CMA European-equity return minus a configured dividend
  yield (the Euro Stoxx 50 is a price index, as in real autocalls). Volatility comes from
  history.

**9.2 Goal buckets (goal-based investing).**
- The emergency fund (Livret A) comes first and is separate.
- Each goal then gets its own **bucket**, funded by assigned existing assets plus a share of
  monthly contributions. Allocation runs in priority order (`essential` before `aspirational`),
  then by date.
- Each bucket's risk level = min(client profile, horizon cap): < 3 y → max 2, 3–5 y → max 3,
  5–8 y → max 4, otherwise the client profile.
- Wrappers are chosen per bucket with the §6.6 rules.
- The Monte Carlo runs per bucket. `fact_goals` stores the bucket, its funding and its wrapper
  split.
- Goal targets are entered in today's euros and inflated at 2 %/yr (configurable).

**9.3 How profile, wrappers and optimiser combine.**
- The optimiser runs per bucket on the **risky sleeve** (ETFs). The safe sleeve (fonds en
  euros / Livret A) has a share set by `profiles.yaml`.
- The volatility cap applies to the **whole bucket**, so the risky-sleeve cap = cap ÷ (1 − safe
  share).
- `profiles.yaml` (own scale, documented as **not** calibrated to the PRIIPs SRI bands):

  | Profile | Vol cap | Max equity | Min safe share |
  |---|---|---|---|
  | 1 | 2 % | 0 % | 80 % |
  | 2 | 4 % | 20 % | 60 % |
  | 3 | 7 % | 40 % | 40 % |
  | 4 | 10 % | 60 % | 25 % |
  | 5 | 13 % | 75 % | 10 % |
  | 6 | 16 % | 90 % | 0 % |
  | 7 | 20 % | 100 % | 0 % |

**9.4 Sample clients and the review timeline.**
- Exact expected profiles: client 1 → 3, client 2 → 4, client 3 → 6, client 4 → 2. Tests
  assert these exactly. The builder invents consistent client data.
- "Now" = the snapshot's last price date.
- Clients 2 and 3 have an original proposal stored in their JSON, dated 18 months before
  "now". Their current holdings are **derived**: the proposal weights are applied at that date
  with historical prices, then monthly contributions are added. Review performance is
  therefore computed from real history.

**9.5 Numeric consistency check for AI documents.**
- Every number is extracted: percentages, euro amounts, years, ages, counts. EN (1,234.5) and
  FR (1 234,5) formats are normalised.
- Each number must match a value in the facts JSON at its displayed precision: ±0.5 percentage
  points, ±1 % of amounts (minimum 1 €). Years and ages must match exactly. "About/environ"
  does not relax the rule.
- On failure the generator gets one retry with the list of mismatches. After that it is a
  hard failure, shown to the advisor, and no document is produced.
- The cache key is a hash of the facts JSON plus the prompt version, so a changed engine
  output invalidates the cache automatically.

**9.6 Structured products.**
- "Knowledge declared" applies to the questionnaire's *structured products* family.
- The 15 % cap is measured on investable assets after the emergency fund.
- Holding place: inside assurance-vie as a unit-linked product (common in France), otherwise
  CTO. Taxation follows the wrapper.
- The autocall is described as **conditional** capital protection ("capital repaid at maturity
  unless the index has fallen more than 40 %"), never as "capital protected". The
  capital-protected note offers full protection at maturity.

**9.7 Simplified 2026 tax rules (`tax_rules.yaml`, fixed, `as_of` 2026).**

| Wrapper | Rule |
|---|---|
| PEA | Withdrawal < 5 y: 30 % on gains (12.8 % + 17.2 %). ≥ 5 y: 17.2 % on gains. |
| Assurance-vie | < 8 y: 30 % on gains. ≥ 8 y: 24.7 % (7.5 % + 17.2 %) on gains after an annual allowance of 4,600 € single / 9,200 € couple. |
| CTO | 30 % on gains; cost basis = weighted average cost (*PRU*). |
| Livret A | Tax-free. |

Stated as a simplification in the methodology. No IR option, no inheritance rules.

**9.8 Data and output practicalities.**
- PDF with reportlab, using built-in fonts (cover é, à, ç, €).
- Data-quality gap rules apply within each ETF's own history, and short histories use the
  §9.1 proxy.
- No network at app runtime.

## 10. Left to the builder
- Exact questionnaire wording and score weights (must produce the expected profile for each
  sample client and be documented).
- Exact ETF list within the stated asset classes and issuers.
- Chart library choices, page layout details, PDF styling.
- Module boundaries inside each package, as long as each component in §6 is testable alone.

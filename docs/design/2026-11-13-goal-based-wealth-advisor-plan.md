# Goal-Based Wealth Advisor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bank-advisor tool (Streamlit, English UI) that profiles a client (MiFID II), builds goal-based proposals across French wrappers with three optimisers and Monte Carlo goal probabilities, runs annual reviews with rebalancing trades, and drafts bilingual (EN/FR) AI letters checked against engine numbers.

**Architecture:** Python package `wealthadvisor` with pure engine modules (suitability, portfolio, wrappers, goals, structured, review) fed by YAML config and a DuckDB price warehouse; an orchestration layer builds `Proposal` / `Review` objects and a `facts` dict; the AI layer turns facts into documents and verifies every number; Streamlit + reportlab render them. Same patterns as project 1 (`cac40-valuation-ai`): committed parquet snapshot, committed AI cache, no network in tests or app.

**Tech Stack:** Python 3.11+, pandas≥2.2, numpy, scipy, PyPortfolioOpt, scikit-learn (Ledoit-Wolf), yfinance, duckdb≥1.1, pandera≥0.24, pydantic v2, pyyaml, anthropic, reportlab, plotly, streamlit≥1.50, pytest, ruff, GitHub Actions.

**Spec:** `docs/design/2026-11-13-goal-based-wealth-advisor-design.md` (sections §6 and §9 are binding).

## Global Constraints

- UI, code, comments, docs in English; AI documents in English **and** French; README ends with "Résumé en français".
- Disclaimer "Educational project — not investment advice" on every app page, PDF and AI document.
- No network in tests, CI or the app; app reads only committed files (`data/snapshot/`, `data/clients/`, `data/ai_cache/`, `config/`).
- LLM model only in `config/settings.yaml` (default `claude-sonnet-5-5`); API used only with `--refresh` + `ANTHROPIC_API_KEY`.
- Profile table (§9.3) verbatim: vol cap 2/4/7/10/13/16/20 %, max equity 0/20/40/60/75/90/100 %, min safe share 80/60/40/25/10/0/0 % for profiles 1–7.
- Bucket horizon caps (§9.2): < 3 y → 2, 3–5 y → 3, 5–8 y → 4, else client profile.
- Risky-sleeve vol cap = bucket cap ÷ (1 − safe share).
- Expected profiles of sample clients: 1→3, 2→4, 3→6, 4→2 (exact).
- Livret A cap 22,950 €; fonds en euros default 2.5 %/yr; inflation 2 %/yr; PEA contribution cap 150,000 €.
- Tax (§9.7): PEA <5 y 30 %, ≥5 y 17.2 % on gains; AV <8 y 30 %, ≥8 y 24.7 % on gains after allowance 4,600 € (single) / 9,200 € (couple); CTO 30 % on gains with weighted-average cost; Livret A 0.
- Structured eligibility: profile ≥ 4, horizon ≥ 8 y, knowledge of family `structured`, allocation ≤ 15 % of investable assets after emergency fund; autocall described as **conditional** protection.
- Monte Carlo: 10,000 paths, monthly, fixed seed (config `seed: 42`).
- Numeric check (§9.5): ±0.5 pp for percentages, ±1 % (min 1 €) for amounts, exact for years/ages; one retry then hard failure; cache key = sha256(facts JSON + prompt version).
- Drift rebalance band default ±5 percentage points per asset class.

## Review Focus

1. **Bucket with zero or negative funding** (goal unaffordable): engine must return probability 0 and a clear "underfunded" flag, not crash or divide by zero. → Task 6.
2. **Safe share = 100 %** (profile 1 bucket) makes risky-sleeve cap divide by zero: skip optimisation, bucket = safe assets only. → Task 4.
3. **Livret A already at cap / client with less than the emergency fund**: allocation fills what it can and records a shortfall rule, never exceeds the cap. → Task 5.
4. **French-formatted numbers and non-breaking spaces** in AI text ("1 234,5 €", "12,5 %"): parsed correctly, not split into two numbers. → Task 9.
5. **Excluded structured product**: never appears in weights, facts or letters as recommended; the exclusion reason does appear. → Tasks 7, 8, 9.

---

## File structure

```
pyproject.toml, Makefile, .gitignore, requirements.txt, .github/workflows/ci.yml
config/settings.yaml, etfs.yaml, rates.yaml, tax_rules.yaml, structured.yaml,
       capital_market_assumptions.yaml, profiles.yaml, questionnaire.yaml
wealthadvisor/
  config.py                    # typed loaders for all YAML
  data/ingest.py, warehouse.py, schema.sql, quality.py, snapshot.py
  clients/models.py            # pydantic Client, Goal, Holding, Answers
  suitability/scoring.py, products.py
  portfolio/riskmodel.py, optimise.py
  wrappers/allocate.py, tax.py
  goals/montecarlo.py
  structured/payoff.py
  proposal.py                  # orchestration New client → Proposal + facts
  review/engine.py             # orchestration Annual review → Review + facts
  ai/client.py, documents.py, numbers.py, prompts/*.md
  outputs/pdf.py
  pipeline.py                  # CLI: ingest, snapshot, quality, AI refresh
app/streamlit_app.py, app/pages/*.py, app/charts.py
data/clients/*.json, data/snapshot/*.parquet, data/ai_cache/
tests/ (mirrors package)
docs/ business_requirements.md, data_dictionary.md, data_model.md, methodology.md
```

---

### Task 1: Scaffold, config loaders and CI

**Files:** Create pyproject, Makefile (`install test lint pipeline app`), .gitignore (`.venv/ data/raw/ data/*.duckdb .env`), CI (Python 3.11, pip cache, ruff, pytest), all `config/*.yaml`, `wealthadvisor/config.py`. Test: `tests/test_config.py`.

**Interfaces (Produces):**
- `@dataclass ETF(ticker, isin, name, asset_class, pea_eligible: bool, sri: int, ter: float, proxy: str | None, unverified: bool)`
- `@dataclass ProfileRule(profile: int, vol_cap: float, max_equity: float, min_safe_share: float)`
- `@dataclass Settings(llm_model, seed, n_paths, inflation, drift_band, prompt_version)`
- `load_etfs() -> list[ETF]`, `load_profiles() -> dict[int, ProfileRule]`, `load_rates() -> dict` (keys `fonds_euros`, `livret_a_rate`, `livret_a_cap`, each with source/as_of), `load_tax_rules() -> dict`, `load_cma() -> dict[str, float]` (asset_class → expected return), `load_structured() -> dict`, `load_questionnaire() -> dict`, `load_settings() -> Settings`. All default paths relative to the repo root resolved from `Path(__file__)` (not cwd).
- Asset classes (exact keys): `equity_world, equity_europe, equity_us, equity_em, bond_gov_euro, bond_corp_euro, bond_inflation_euro`. Equity classes = names starting `equity_`.

- [ ] **Step 1:** Failing tests: profiles table equals Global Constraints exactly; every ETF's asset_class has a CMA entry; at least one PEA-eligible ETF per equity class used by PEA (`equity_world`, `equity_europe`); 12 ≤ len(etfs) ≤ 15; settings defaults (`seed==42`, `n_paths==10000`, `inflation==0.02`, `drift_band==0.05`); rates contain source and as_of.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. ETF list: real UCITS ETFs on Euronext Paris from Amundi / iShares / BNP Paribas Easy; set `unverified: true` for any ISIN/PEA/SRI not checked against an issuer factsheet. CMA: one published long-term CMA (cite source + date in YAML).
- [ ] **Step 4:** `pytest -q && ruff check .` → PASS.
- [ ] **Step 5:** Commit `chore: scaffold package, config and CI`.

---

### Task 2: Price data, proxy back-fill, warehouse, quality, snapshot

**Files:** `wealthadvisor/data/{ingest,warehouse,schema.sql,quality,snapshot}.py`, `wealthadvisor/pipeline.py` (subcommand `ingest`). Tests `tests/data/*`, fixture `tests/fixtures/prices_sample.csv`.

**Interfaces:**
- Tables: `dim_product(ticker, isin, name, asset_class, pea_eligible, sri, ter)`, `fact_prices(ticker, date, adj_close, is_proxy)`, `dim_client(client_id, name, profile_expected)`, `fact_goals(client_id, goal_id, bucket_risk, funding_now, monthly_contribution, target_nominal, date)`, `fact_holdings(client_id, wrapper, ticker, units, avg_cost, as_of)`, `fact_proposals(client_id, created_at, payload_json)`, `fact_ai_documents(client_id, doc_type, lang, cache_key, text, created_at)`.
- `fetch_monthly(ticker: str) -> pd.Series` (network; month-end adj close, saves raw under `data/raw/`).
- `backfill_with_proxy(etf: pd.Series, proxy: pd.Series) -> tuple[pd.Series, pd.Series]` → (series, is_proxy flags): before the ETF's first date, chain proxy returns backwards from the ETF's first price.
- `connect(path=":memory:"|"data/warehouse.duckdb")`, `upsert(con, table, df)` (whitelisted tables), `monthly_returns(con, tickers, start=None) -> pd.DataFrame`.
- `run_quality_checks(con) -> list[QualityIssue]` (gap > 1 month within a ticker's own history, non-positive price, config ETF without prices, PEA holding of non-eligible ETF, Livret A balance > cap), `write_quality_report(...)`.
- `export_snapshot(con, dir="data/snapshot")`, `load_snapshot(dir) -> duckdb connection`.

- [ ] **Step 1:** Failing tests: backfill on fixture (proxy returns chained, first ETF price unchanged, flags correct); quality flags a 2-month gap and a negative price; snapshot round-trip; upsert unknown table → ValueError.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Real run (network) `python -m wealthadvisor.pipeline ingest` for all ETFs + `^STOXX50E`; export snapshot; commit `data/snapshot/*.parquet` and `data_quality_report.md`. Report history length per ETF and which use proxies.
- [ ] **Step 6:** Commit `feat(data): prices, proxy back-fill, warehouse, quality, snapshot`.

---

### Task 3: Client model, sample clients, questionnaire and suitability

**Files:** `wealthadvisor/clients/models.py`, `wealthadvisor/suitability/{scoring,products}.py`, `config/questionnaire.yaml`, `data/clients/{c1_young_professional,c2_couple_retirement,c3_business_owner,c4_retiree}.json`. Tests `tests/suitability/*`, `tests/clients/*`.

**Interfaces:**
- pydantic: `Goal(goal_id, label, target_today_eur: float, date: date, priority: Literal["essential","aspirational"])`, `Holding(wrapper: Literal["livret_a","pea","av","cto"], ticker: str | None, product: str, units: float, avg_cost: float)` (`ticker None` for fonds euros / Livret A, `product` in {`etf`,`fonds_euros`,`livret_a`,`structured:<id>`}), `Answers(dict[str, str])`, `Client(client_id, name, age, household: Literal["single","couple"], annual_income, monthly_expenses, liquid_assets, debts, monthly_saving, goals: list[Goal], answers: Answers, original_proposal: dict | None, proposal_date: date | None)`.
- `load_client(path) -> Client`, `list_sample_clients() -> list[Client]`.
- `score_profile(client: Client) -> ProfileResult` with `ProfileResult(profile: int, raw_score: float, rules_fired: list[str], knowledge: dict[str, bool])`. Deterministic: weighted section scores → raw profile 1–7; cap rules (horizon < 3 y caps at 2, loss capacity "low" caps at 3, etc.); each applied rule appended to `rules_fired` as an English sentence.
- `check_product(product_family: str, client: Client, profile: ProfileResult, horizon_years: float) -> Suitability(included: bool, reasons: list[str])`. Families: `livret_a, fonds_euros, etf_bond, etf_equity, structured`.

- [ ] **Step 1:** Failing tests: each sample client scores exactly its expected profile; a client with 2-year horizon and high tolerance is capped at 2 with that rule in `rules_fired`; `check_product("structured", c4, …)` excluded with ≥1 reason; `check_product("structured", c3, …)` included.
- [ ] **Step 2–4:** RED → implement (write the four JSON clients, consistent data; c2 and c3 include `original_proposal` (wrapper → product → amount €) and `proposal_date` = the snapshot's last price date (from Task 2) minus 18 months, written into the JSON) → GREEN.
- [ ] **Step 5:** Commit `feat(suitability): client model, sample clients, MiFID scoring and product suitability`.

---

### Task 4: Risk model and optimisers

**Files:** `wealthadvisor/portfolio/{riskmodel,optimise}.py`. Tests `tests/portfolio/*`.

**Interfaces:**
- `covariance(returns: pd.DataFrame) -> pd.DataFrame` (Ledoit-Wolf, annualised ×12).
- `expected_returns(tickers, etfs, cma) -> pd.Series` (ticker → CMA of its asset class).
- `portfolio_stats(weights: pd.Series, mu, cov, safe_share: float, safe_rate: float) -> dict(expected_return, volatility)` (bucket-level: risky sleeve scaled by 1 − safe_share, safe sleeve vol 0).
- `optimise(method: Literal["markowitz","black_litterman","hrp"], tickers, mu, cov, returns, rule: ProfileRule, safe_share: float, max_equity_in_sleeve: float, views: dict[str, float] | None = None) -> OptResult(weights: pd.Series, expected_return, volatility, max_drawdown, method)`.
  - If `safe_share >= 1`: return empty weights (Review Focus 2).
  - Risky-sleeve vol cap = rule.vol_cap / (1 − safe_share); equity weight in sleeve ≤ max_equity_in_sleeve.
  - Markowitz: PyPortfolioOpt `EfficientFrontier.efficient_risk(cap)`; if infeasible, `min_volatility()` and record a note.
  - Black-Litterman: equilibrium returns from reference weights in `capital_market_assumptions.yaml` (`reference_weights` by asset class), risk aversion δ = 2.5, optional views; then the same efficient_risk call on BL posterior.
  - HRP: `HRPOpt`; then scale down if sleeve vol > cap by shifting the excess to the lowest-vol bond ETF (documented).
  - `max_drawdown` from historical monthly returns of the weighted sleeve.
- All three returned stats evaluated with the same `mu` (CMA) and `cov` (design §9.1).

- [ ] **Step 1:** Failing tests on a synthetic 4-asset return set: weights sum to 1, non-negative; sleeve vol ≤ cap + 1e-6 for each method; equity share ≤ limit; `safe_share=1` → empty weights; stats use CMA mu for all methods (same mu → identical expected_return function).
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat(portfolio): risk model and Markowitz/BL/HRP optimisers`.

---

### Task 5: Goal buckets, wrapper allocation and tax

**Files:** `wealthadvisor/wrappers/{allocate,tax}.py`. Tests `tests/wrappers/*`.

**Interfaces:**
- `bucket_risk(client_profile: int, horizon_years: float) -> int` (caps from Global Constraints).
- `plan_buckets(client: Client, profile: int, today: date, rates, settings) -> BucketPlan(emergency: EmergencyFund(target, funded, shortfall, rules: list[str]), buckets: list[Bucket])`, `Bucket(goal_id, horizon_years, risk: int, funding_now: float, monthly_contribution: float, target_nominal: float, wrapper_split: dict[str, float], safe_share: float, rules: list[str])`.
  - Emergency fund = 6 × monthly_expenses if profile ≤ 3 else 3 ×, capped at Livret A cap; shortfall recorded (Review Focus 3).
  - Remaining liquid assets and monthly saving allocated to buckets: essential first, then by date; proportional to inflated targets within the same priority.
  - Wrapper split per §6.6 rules (PEA for equity when horizon ≥ 5 y and contributions ≤ 150,000 €; AV for safe share + rest when horizon ≥ 3 y; Livret A for < 3 y safe money within cap; CTO overflow). Each rule appended to `rules`.
  - `target_nominal = target_today × (1 + inflation) ** years`.
- `tax_on_gain(wrapper, gain: float, years_held: float, household: str) -> float` (Global Constraints table; gain ≤ 0 → 0).
- `weighted_average_cost(lots: list[tuple[units, price]]) -> float`.

- [ ] **Step 1:** Failing tests: `bucket_risk(6, 2)==2`, `(6,4)==3`, `(6,6)==4`, `(6,10)==6`, `(2,10)==2`; tax: PEA gain 1000 at 6 y → 172, at 3 y → 300; AV gain 10000 at 9 y single → (10000−4600)×0.247 = 1333.8, couple → 197.6; CTO 1000 → 300; Livret A → 0; negative gain → 0; emergency fund never exceeds 22,950 and shortfall recorded when liquid assets are short; target inflation 100,000 € over 10 y → 121,899.44.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat(wrappers): goal buckets, wrapper allocation and simplified French tax`.

---

### Task 6: Goal Monte Carlo

**Files:** `wealthadvisor/goals/montecarlo.py`. Tests `tests/goals/*`.

**Interfaces:**
- `simulate_bucket(bucket: Bucket, weights: pd.Series, mu: pd.Series, cov: pd.DataFrame, safe_rate: float, n_paths: int, seed: int, household: str) -> GoalResult(goal_id, probability: float, p10, p50, p90: float, paths_quantiles: pd.DataFrame (month × [p10,p50,p90]), underfunded: bool)`.
  - Monthly steps to goal date; risky sleeve returns ~ multivariate normal with monthly mean `(1+mu)**(1/12)-1` and cov/12; safe sleeve grows at `(1+safe_rate)**(1/12)-1`; contributions added at month end split by safe_share.
  - After-tax value at goal date: gains taxed per wrapper_split with `tax_on_gain` (years = horizon).
  - Probability = share of paths with after-tax value ≥ target_nominal.
  - Zero/negative funding and contribution → probability 0, `underfunded=True` (Review Focus 1).

- [ ] **Step 1:** Failing tests: zero-vol sleeve + deterministic rate gives probability 1 when deterministic value ≥ target and 0 when below; same seed → identical result; underfunded bucket → 0 and flag; quantiles ordered p10 ≤ p50 ≤ p90.
- [ ] **Step 2–4:** RED → implement (vectorised numpy) → GREEN.
- [ ] **Step 5:** Commit `feat(goals): Monte Carlo goal probabilities`.

---

### Task 7: Structured products

**Files:** `wealthadvisor/structured/payoff.py`, `config/structured.yaml`. Tests `tests/structured/*`.

**Interfaces:**
- Templates in YAML: `autocall_sx5e` (8 y, annual obs, autocall + coupon `c` per elapsed year if index ≥ 100 %, barrier 60 % at maturity, coupon rate configurable e.g. 7 %/yr) and `cpn_sx5e` (8 y, 100 % capital at maturity + participation `p` × max(0, index return)).
- `simulate_index(s0=1.0, mu: float, sigma: float, years: int, n_paths, seed) -> np.ndarray` (annual GBM levels; mu = CMA equity_europe − dividend_yield from YAML; sigma from historical `^STOXX50E` monthly returns ×√12).
- `autocall_payoff(levels: np.ndarray, coupon, barrier) -> PayoffResult(payoff_multiple: np.ndarray, called_year: np.ndarray, prob_capital_loss: float, expected_multiple: float, describe: str)` — `describe` uses conditional wording: "capital repaid at maturity unless the index has fallen more than 40 %".
- `cpn_payoff(levels, participation) -> PayoffResult`.
- `structured_allocation(client, profile, bucket_plan) -> StructuredDecision(included: bool, product_id, amount: float, wrapper: Literal["av","cto"], reasons: list[str], payoff: PayoffResult | None)` — uses `check_product("structured", …)`; amount ≤ 15 % of investable assets after emergency fund; wrapper = `av` if any bucket uses AV else `cto`.

- [ ] **Step 1:** Failing tests: hand paths — path at 105 % in year 1 → called year 1, payoff 1 + c; path ending at 55 % never called → payoff 0.55; path ending at 70 % never called → 1.0; CPN path ending at 120 % with p=0.5 → 1.10; `describe` contains "unless" and not "capital protected"; c4 → excluded with reasons; c3 → included, amount ≤ 15 % cap.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat(structured): autocall and capital-protected note payoffs with eligibility`.

---

### Task 8: New-client proposal orchestration and facts

**Files:** `wealthadvisor/proposal.py`. Tests `tests/test_proposal.py`.

**Interfaces:**
- `build_proposal(client: Client, con, method_override: dict[str, str] | None = None, views: dict | None = None) -> Proposal` with `Proposal(client_id, as_of: date, profile: ProfileResult, emergency, buckets: list[BucketProposal], structured: StructuredDecision, totals: dict)`, `BucketProposal(bucket: Bucket, methods: dict[str, OptResult], chosen: str, goal: GoalResult, holdings_eur: dict[wrapper, dict[product, float]])`.
  - Default chosen method: `hrp` if bucket.risk ≤ 3 else `black_litterman`; `method_override[goal_id]` wins.
  - Investable universe per wrapper: PEA → PEA-eligible ETFs only; AV/CTO → all ETFs.
  - If structured included, its amount is taken from the longest-horizon bucket's risky sleeve before optimisation (rule recorded).
- `proposal_facts(p: Proposal) -> dict` — JSON-serialisable; every number the documents may cite (profile, rules_fired, emergency target/shortfall, per-goal target, probability as %, p10/p50/p90, wrapper amounts, chosen method, expected return/vol, structured included/excluded + reasons + prob of capital loss, disclaimer). Rounded to display precision (percent 1 dp, euros 0 dp).
- Persist: `save_proposal(con, p)` → `fact_proposals`.

- [ ] **Step 1:** Failing tests using the snapshot fixture DB (or `tests/fixtures` synthetic DB): for each sample client a proposal builds; wrapper amounts + emergency = liquid assets (±1 €); PEA holdings only PEA-eligible; c4 facts show structured excluded with reasons and no structured amount anywhere (Review Focus 5); facts JSON-serialisable.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat: new-client proposal orchestration and facts`.

---

### Task 9: AI documents with numeric verification

**Files:** `wealthadvisor/ai/{client,documents,numbers}.py`, `wealthadvisor/ai/prompts/{proposal_v1,review_v1}.md`. Tests `tests/ai/*`.

**Interfaces:**
- `extract_numbers(text: str, lang: Literal["en","fr"]) -> list[NumberToken(value: float, kind: Literal["percent","eur","year","age","plain"], raw: str)]` — handles "1,234.5", "1 234,5 €" (incl. U+00A0 / U+202F), "12,5 %", "12.5%", "€1,200", years 1900–2100.
- `verify(text, lang, facts) -> list[str]` (mismatch messages; empty = OK) with tolerances from Global Constraints; numbers are matched against all numeric leaves of `facts` (percent leaves compared in pp).
- `LLMClient` protocol; `AnthropicClient` (lazy import, key from env, model from settings, forced tool `write_document` returning `{"title": str, "body": str}`, raise on `stop_reason == "max_tokens"`).
- `generate(doc_type: Literal["proposal_advisor","proposal_client","review_advisor","review_client"], lang, facts, client: LLMClient | None, refresh: bool, cache_dir=Path("data/ai_cache")) -> Document(doc_type, lang, title, body, cache_key, verified: bool, errors: list[str])`.
  - cache_key = sha256(json.dumps(facts, sort_keys=True) + prompt_version + doc_type + lang).
  - Cache hit and not refresh → return cached. Miss and no client → `None` with a clear log.
  - Generate → verify → if errors, one retry with the error list appended → if still errors, `verified=False`, body not shown by the app.
  - Prompt: facts given as JSON inside `<facts>` tags; instructions: use only these numbers and recommendations; letter tone for client docs, technical for advisor docs; French docs in natural French (vouvoiement); always end with the disclaimer in the document's language.
- Pipeline CLI: `python -m wealthadvisor.pipeline ai --refresh` builds proposals (and reviews after Task 11) for all sample clients and writes cache.

- [ ] **Step 1:** Failing tests: extract_numbers on EN/FR samples incl. NBSP (Review Focus 4); verify passes on a matching letter and flags "65 %" when facts say 72.3 %; year mismatch flagged; fake client returning a wrong number then a correct one → verified after retry; fake client wrong twice → `verified=False`; cache key changes when one fact changes; max_tokens raise.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat(ai): bilingual documents with numeric verification and cache`. (Real generation needs the user's API key — user step.)

---

### Task 10: Streamlit app (New client) and PDF

**Files:** `app/streamlit_app.py`, `app/pages/{1_New_client,3_Product_universe,4_Data_quality,5_About}.py`, `app/charts.py`, `wealthadvisor/outputs/pdf.py`, `requirements.txt`. Tests `tests/app/*`, `tests/outputs/test_pdf.py`.

**Interfaces / behaviour:**
- App reads `load_snapshot()`, sample clients, AI cache only; `os.chdir` to repo root; cached resources.
- New client page: client selector (samples + "Blank client" form); sections in order of design §5 (situation, questionnaire with editable answers → profile + rules fired, wrapper plan table, per-bucket method comparison with a selectbox to pick the method, goal fan charts + probability, structured included/excluded with reasons and payoff histogram, AI documents in tabs EN/FR advisor/client — show "Not generated yet (run with --refresh)" when missing and a red warning if `verified=False`), PDF download (EN or FR).
- `charts.py`: `fan_chart(GoalResult)`, `allocation_sunburst(proposal)`, `method_comparison(bucket_proposal)`, `payoff_histogram(PayoffResult)` — pure plotly.
- `pdf.py`: `proposal_pdf(proposal, facts, documents: dict[lang, Document | None], lang) -> bytes` with reportlab built-in fonts; includes letter (if verified), key tables, disclaimer.
- Footer on every page: disclaimer + data as-of date.

- [ ] **Step 1:** Failing tests: AppTest runs New client page for all 4 clients without exception; changing a method selectbox changes displayed expected return; PDF bytes start with `%PDF` and contain "not investment advice"/"pas un conseil en investissement" per lang (extract with pymupdf or check reportlab text); charts return figures.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Manual: `streamlit run` headless, `/_stcore/health` ok.
- [ ] **Step 6:** Commit `feat(app): new-client workflow and PDF export`.

---

### Task 11: Annual review engine

**Files:** `wealthadvisor/review/engine.py`. Tests `tests/review/*`.

**Interfaces:**
- `derive_holdings(client: Client, con, as_of: date) -> list[Holding]` — apply `original_proposal` wrapper/product amounts at `proposal_date` using historical prices (units = amount / price), add monthly contributions split as in the proposal at each month end, fonds euros/Livret A accrue at their rates; avg_cost tracked (weighted average).
- `build_review(client: Client, con, as_of: date | None = None, new_answers: Answers | None = None) -> Review(client_id, as_of, performance: dict[wrapper|"total", twr: float, gain_eur: float], drift: pd.DataFrame (asset_class × [target, current, diff]), profile_before: int, profile_now: ProfileResult, profile_changed: bool, goals_before: list[GoalResult], goals_now: list[GoalResult], trades: list[Trade(wrapper, product, action: Literal["buy","sell"], amount_eur, taxable: bool, est_tax_eur)])`.
  - as_of default = last snapshot date; proposal_date = as_of − 18 months (if JSON date differs, JSON wins).
  - TWR monthly chain-linked with contributions at month end.
  - Rebalance only asset classes with |diff| > drift_band; trades restore target weights within each wrapper first; cross-wrapper moves only via new contributions; CTO sells flagged `taxable` with `tax_on_gain`.
  - goals_now re-simulated from current values.
- `review_facts(r: Review) -> dict` (same rounding rules as proposal_facts).

- [ ] **Step 1:** Failing tests on a synthetic DB with known prices: derive_holdings units = amount/price at start; TWR of a constant-price portfolio with contributions = 0; a +10 % drift produces a sell of the over-weight class and buy of the under-weight class summing to ~0 within the wrapper; CTO sell flagged with tax = 30 % of gain on average cost; profile change flagged when answers change; c2 and c3 reviews build on the real snapshot.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat(review): annual review engine`.

---

### Task 12: Annual review page, review PDF and review AI docs

**Files:** `app/pages/2_Annual_review.py`, extend `app/charts.py` (`drift_bars`, `goal_probability_change`), `outputs/pdf.py` (`review_pdf`), pipeline `ai --refresh` covers reviews. Tests extend `tests/app`, `tests/outputs`.

- [ ] **Step 1:** Failing tests: AppTest Annual review for c2 and c3 without exception (c1/c4 show "No existing portfolio for this client"); editing a questionnaire answer updates "profile changed"; review PDF EN/FR bytes valid with disclaimer.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat(app): annual review workflow, PDF and AI review documents`.

---

### Task 13: Documentation, README, final data run

**Files:** `README.md`, `docs/{business_requirements,data_dictionary,data_model,methodology}.md`, `LICENSE` (MIT, "Copyright (c) 2026 goal-based-wealth-advisor contributors"), `scripts/readme_results.py` (sample-client table from facts: client, profile, goals, probabilities, structured decision), `docs/img/*` (fan chart, allocation, method comparison PNGs via plotly→kaleido or matplotlib re-plots).

- Business requirements: stakeholders (advisor, compliance officer, client), 8 user stories with acceptance criteria (onboarding, suitability trace, structured exclusion, proposal letter EN/FR, annual review, rebalancing, data quality, no-key demo), KPI definitions (goal probability, drift, TWR, suitability coverage).
- Methodology: every rule and formula, the profile table, bucket caps, tax table, CMA source, proxy policy, structured templates with conditional-protection wording, numeric-check policy, limitations (simplified tax, fictional clients, CMA dependence, normal returns, no real products).
- README order: title + CI badge + live demo link placeholder → business problem → screenshots (generated charts, not fake app screenshots) → sample-client results table → how it works (Mermaid) → suitability & AI guardrails → data governance → quickstart → project structure → limitations → disclaimer → Résumé en français (~120 words).
- GitHub owner is `dmp009`: use it directly in badge and clone URLs.

- [ ] **Step 1:** Write docs; check every table in schema.sql is in the data dictionary.
- [ ] **Step 2:** `make test && make lint` pass; fresh run without API key: `make app` works on committed files.
- [ ] **Step 3:** Commit `docs: README, business requirements, data dictionary, methodology`.

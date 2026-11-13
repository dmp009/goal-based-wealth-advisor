# Data dictionary

Warehouse: DuckDB file `data/warehouse.duckdb` (not committed), created from
[`wealthadvisor/data/schema.sql`](../wealthadvisor/data/schema.sql) by
`python -m wealthadvisor.pipeline ingest`. A parquet copy of every table is committed in
`data/snapshot/<table>.parquet`; the app and the tests load it into an in-memory DuckDB
(`wealthadvisor.data.snapshot.load_snapshot`).

Writes go through `wealthadvisor.data.warehouse.upsert`: rows matching the incoming natural
key are deleted, then the new rows are inserted, in one transaction. Only the seven tables
below are accepted, and a missing column is an error. Re-running the pipeline is idempotent.

Row counts are from the committed snapshot (last price date 31 October 2026).

| Table | Type | Grain (natural key) | Rows in snapshot |
|---|---|---|--:|
| `dim_product` | Dimension | `ticker` | 14 |
| `fact_prices` | Fact | `ticker`, `date` | 2,736 |
| `dim_client` | Dimension | `client_id` | 0 |
| `fact_goals` | Fact | `client_id`, `goal_id` | 0 |
| `fact_holdings` | Fact | `client_id`, `wrapper`, `ticker`, `as_of` | 0 |
| `fact_proposals` | Fact | `client_id`, `created_at` | 0 |
| `fact_ai_documents` | Fact | `client_id`, `doc_type`, `lang`, `cache_key` | 0 |

**Why five tables are empty.** The sample clients live as JSON in `data/clients/`, their
current holdings are derived at run time from the original proposal and real prices (see
[methodology, section 9](methodology.md)), and AI documents are cached as JSON in
`data/ai_cache/`. The client-side tables are defined, covered by the upsert and quality tests,
and `save_proposal` writes `fact_proposals`, but the ingest pipeline does not populate them.

## dim_product

One row per ETF in `config/etfs.yaml`. The Euro Stoxx 50 index (`^STOXX50E`) has prices but no
product row, because it is not an investable product here (only the underlying of the
structured templates).

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `ticker` | VARCHAR | Yahoo Finance ticker on Euronext Paris, e.g. `CW8.PA`. Natural key. | `config/etfs.yaml` | None |
| `isin` | VARCHAR | ISIN of the fund | `config/etfs.yaml` (justETF, pea.fr) | None |
| `name` | VARCHAR | Fund name | `config/etfs.yaml` | None |
| `asset_class` | VARCHAR | One of `equity_world`, `equity_europe`, `equity_us`, `equity_em`, `bond_gov_euro`, `bond_corp_euro`, `bond_inflation_euro`. Links to the CMA returns and BL reference weights. | `config/etfs.yaml` | None |
| `pea_eligible` | BOOLEAN | TRUE / FALSE when confirmed by a source; NULL when unknown (7 ETFs). NULL is treated as not eligible everywhere. | `config/etfs.yaml` | None |
| `sri` | INTEGER | PRIIPs summary risk indicator 1-7. NULL for every ETF: no value could be confirmed, none is guessed. | `config/etfs.yaml` | None |
| `ter` | DOUBLE | Total expense ratio as a fraction (0.0038 = 0.38 %) | `config/etfs.yaml` (justETF) | None |

The config also carries `proxy`, `sources` and `unverified_fields` per ETF; they are used by the
ingest and shown on the Product universe page but not stored in the table.

## fact_prices

Month-end adjusted closes for the 14 ETFs and `^STOXX50E`, from their first available month
to the last complete month.

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `ticker` | VARCHAR | ETF ticker or `^STOXX50E`. Part of the key. | yfinance | None |
| `date` | DATE | Calendar month end. Part of the key. | yfinance | Daily closes resampled to the last close of each month; the current, incomplete month is dropped |
| `adj_close` | DOUBLE | Adjusted close (dividends and splits) in EUR; index level for `^STOXX50E` | yfinance `history(auto_adjust=True)` | For back-filled rows: proxy price × (first own price ÷ proxy price at that date) |
| `is_proxy` | BOOLEAN | TRUE when the row comes from the proxy back-fill, FALSE for the ETF's own history | Pipeline | Set by `backfill_with_proxy` |

## dim_client

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `client_id` | VARCHAR | Client identifier, e.g. `c2`. Natural key. | `data/clients/*.json` | None |
| `name` | VARCHAR | Client name (fictional) | `data/clients/*.json` | None |
| `profile_expected` | INTEGER | Expected risk profile 1-7 used as a test reference | Design (§9.4) | None |

## fact_goals

One row per goal bucket of a proposal.

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `client_id` | VARCHAR | Client. Part of the key. | Client JSON | None |
| `goal_id` | VARCHAR | Goal identifier, e.g. `retirement`. Part of the key. | Client JSON | None |
| `bucket_risk` | INTEGER | Risk level of the bucket = min(client profile, horizon cap) | Engine | `wrappers.allocate.bucket_risk` |
| `funding_now` | DOUBLE | Existing assets assigned to the bucket today, EUR | Engine | Priority then date order, up to the present value of the target |
| `monthly_contribution` | DOUBLE | Monthly saving assigned to the bucket, EUR | Engine | Level annuity closing the gap, capped by the saving available |
| `target_nominal` | DOUBLE | Target at the goal date, EUR | Engine | Target in today's euros × (1 + inflation)^years |
| `date` | DATE | Goal date | Client JSON | None |

## fact_holdings

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `client_id` | VARCHAR | Client. Part of the key. | Client JSON | None |
| `wrapper` | VARCHAR | `livret_a`, `pea`, `av` (assurance-vie) or `cto`. Part of the key. | Engine | None |
| `ticker` | VARCHAR | ETF ticker; for fonds en euros, Livret A and structured notes the product key (`fonds_euros`, `livret_a`, `structured:<id>`). Part of the key. | Engine | None |
| `units` | DOUBLE | Units held; for Livret A and fonds en euros one unit = 1 EUR of value | Engine | Amount ÷ month-end price at each purchase |
| `avg_cost` | DOUBLE | Weighted average cost per unit (*PRU*) | Engine | Σ(units × price) ÷ Σ units |
| `as_of` | DATE | Valuation date. Part of the key. | Engine | Snapshot last price date |

Quality checks on this table: PEA holdings must have `pea_eligible = TRUE` in `dim_product`;
the Livret A balance (Σ units × avg_cost) must not exceed the ceiling in `config/rates.yaml`.

## fact_proposals

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `client_id` | VARCHAR | Client. Part of the key. | Engine | None |
| `created_at` | TIMESTAMP | Time the proposal was saved. Part of the key. | Engine | `datetime.now()` unless given |
| `payload_json` | VARCHAR | Full facts JSON of the proposal (`proposal_facts`), the same object the AI documents are written from | Engine | `json.dumps` |

## fact_ai_documents

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `client_id` | VARCHAR | Client. Part of the key. | Pipeline | None |
| `doc_type` | VARCHAR | `proposal_advisor`, `proposal_client`, `review_advisor` or `review_client`. Part of the key. | Pipeline | None |
| `lang` | VARCHAR | `en` or `fr`. Part of the key. | Pipeline | None |
| `cache_key` | VARCHAR | SHA-256 of facts JSON + prompt version + document type + language + prompt template. Part of the key. | Pipeline | `ai.documents.cache_key` |
| `text` | VARCHAR | Verified document text (Markdown) | LLM, verified | Only documents that pass the numeric check |
| `created_at` | TIMESTAMP | Generation time | Pipeline | None |

## Client file (`data/clients/<id>.json`)

Not a warehouse table, but the main input of the engine. Validated by the pydantic model
`wealthadvisor.clients.models.Client`.

| Field | Type | Description |
|---|---|---|
| `client_id`, `name` | string | Identifier and fictional name |
| `age` | integer | Age in years |
| `household` | `single` or `couple` | Sets the assurance-vie allowance (4,600 € or 9,200 €) |
| `annual_income`, `monthly_expenses`, `liquid_assets`, `debts`, `monthly_saving` | number (EUR) | Financial situation. Debts are recorded but not used by the allocation |
| `goals[]` | list | `goal_id`, `label`, `label_fr`, `target_today_eur`, `date`, `priority` (`essential` or `aspirational`) |
| `answers` | object | Question id → answer key, as defined in `config/questionnaire.yaml` |
| `original_proposal` | object or null | Wrapper → product → EUR invested at the proposal date (clients c2 and c3) |
| `proposal_date` | date or null | Date of the original proposal (30 April 2025 for c2 and c3) |

## Configuration files (`config/`)

| File | Content |
|---|---|
| `etfs.yaml` | ETF universe: ticker, ISIN, name, asset class, PEA flag, SRI, TER, proxy, sources, unverified fields |
| `capital_market_assumptions.yaml` | Expected annual return per asset class, Black-Litterman reference weights, source, `as_of`, `unverified` |
| `rates.yaml` | Fonds en euros rate, Livret A rate and ceiling, PEA contribution cap, each with source and `as_of` |
| `tax_rules.yaml` | Simplified 2026 rates and thresholds per wrapper |
| `profiles.yaml` | Volatility cap, maximum equity share and minimum safe share per profile 1-7 |
| `questionnaire.yaml` | Questions, answer scores, section weights, thresholds and cap levels |
| `structured.yaml` | Autocall and capital-protected note templates, dividend yield, 15 % cap, eligibility |
| `settings.yaml` | LLM model, random seed, number of paths, inflation, drift band, prompt version, disclaimers |

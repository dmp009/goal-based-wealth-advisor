# Data model and lineage

## Star schema

Two dimensions (`dim_product`, `dim_client`) and five facts, defined in
[`wealthadvisor/data/schema.sql`](../wealthadvisor/data/schema.sql). Column definitions are in
the [data dictionary](data_dictionary.md).

```mermaid
erDiagram
    dim_product ||--o{ fact_prices : "priced in"
    dim_product ||--o{ fact_holdings : "held as"
    dim_client ||--o{ fact_goals : "has"
    dim_client ||--o{ fact_holdings : "owns"
    dim_client ||--o{ fact_proposals : "receives"
    dim_client ||--o{ fact_ai_documents : "receives"

    dim_product {
        VARCHAR ticker PK
        VARCHAR isin
        VARCHAR name
        VARCHAR asset_class
        BOOLEAN pea_eligible "NULL = unknown, treated as FALSE"
        INTEGER sri "NULL: not verified"
        DOUBLE ter
    }
    fact_prices {
        VARCHAR ticker PK
        DATE date PK
        DOUBLE adj_close
        BOOLEAN is_proxy
    }
    dim_client {
        VARCHAR client_id PK
        VARCHAR name
        INTEGER profile_expected
    }
    fact_goals {
        VARCHAR client_id PK
        VARCHAR goal_id PK
        INTEGER bucket_risk
        DOUBLE funding_now
        DOUBLE monthly_contribution
        DOUBLE target_nominal
        DATE date
    }
    fact_holdings {
        VARCHAR client_id PK
        VARCHAR wrapper PK
        VARCHAR ticker PK
        DATE as_of PK
        DOUBLE units
        DOUBLE avg_cost
    }
    fact_proposals {
        VARCHAR client_id PK
        TIMESTAMP created_at PK
        VARCHAR payload_json
    }
    fact_ai_documents {
        VARCHAR client_id PK
        VARCHAR doc_type PK
        VARCHAR lang PK
        VARCHAR cache_key PK
        VARCHAR text
        TIMESTAMP created_at
    }
```

Notes:

- `fact_prices` also holds `^STOXX50E`, which has no `dim_product` row (index only, used by the
  structured-product simulation). The relation is therefore not enforced as a foreign key.
- `fact_holdings.ticker` also holds non-ETF product keys (`fonds_euros`, `livret_a`,
  `structured:<id>`) that have no `dim_product` row.
- In the committed snapshot only `dim_product` and `fact_prices` are populated. Clients are read
  from `data/clients/*.json`, holdings are derived at run time and AI documents are cached as
  JSON files (see the data dictionary).

## Pipeline and lineage

```mermaid
flowchart TD
    subgraph Ingest ["python -m wealthadvisor.pipeline ingest (network)"]
        YF[yfinance daily history<br/>14 ETFs + ^STOXX50E] --> RAW[data/raw/yfinance/<br/>UTC-timestamped CSV]
        YF --> M[Month-end resample<br/>drop incomplete month]
        M --> BF[Proxy back-fill<br/>is_proxy = true]
        ETFCFG[config/etfs.yaml] --> DP[dim_product]
        ETFCFG --> BF
        BF --> FP[fact_prices]
        DP --> WH[(data/warehouse.duckdb)]
        FP --> WH
        WH --> QC[Quality checks] --> REP[data_quality_report.md]
        WH --> SNAP[data/snapshot/*.parquet<br/>committed]
    end

    subgraph Engine ["Engine (no network)"]
        SNAP --> CON[(In-memory DuckDB)]
        CLI[data/clients/*.json] --> PROP[build_proposal]
        CFG[config/*.yaml] --> PROP
        CON --> PROP
        PROP --> PF[proposal_facts]
        CLI --> REV[build_review]
        CON --> REV
        PROP --> REV
        REV --> RF[review_facts]
    end

    subgraph AI ["python -m wealthadvisor.pipeline ai --refresh (API key)"]
        PF --> LLM[LLM draft EN / FR]
        RF --> LLM
        LLM --> CHK{Numeric check}
        CHK -->|fail| RETRY[One retry with errors]
        RETRY --> CHK2{Numeric check}
        CHK2 -->|fail| REJ[Rejected, not cached]
        CHK -->|pass| CACHE[data/ai_cache/key.json]
        CHK2 -->|pass| CACHE
    end

    PF --> APP[Streamlit app + PDF]
    RF --> APP
    CACHE --> APP
    REP --> APP
    PF --> README[make readme / make figures]
    RF --> README
```

Lineage guarantees:

- **Raw data**: every yfinance response is saved before any transformation, with the UTC time
  of the call in the file name.
- **Back-filled prices**: flagged row by row with `is_proxy`; the ETF's own prices are never
  modified. The proxy used for each ETF is listed in `config/etfs.yaml`.
- **Parameters**: every rate and cap carries a `source` and an `as_of` date; ETF metadata
  carries its sources and the list of unverified fields; the CMA file carries its source and an
  `unverified` flag.
- **Engine outputs**: the facts JSON contains the rules that fired (profile caps, wrapper
  rules, structured-product reasons), so each number can be traced to the rule that produced
  it.
- **AI documents**: the cache key is a hash of the facts, the prompt template and version, the
  document type and the language. A change in any of them produces a new key.

CREATE TABLE IF NOT EXISTS dim_product (
    ticker VARCHAR PRIMARY KEY,
    isin VARCHAR,
    name VARCHAR,
    asset_class VARCHAR,
    pea_eligible BOOLEAN,
    sri INTEGER,
    ter DOUBLE
);
CREATE TABLE IF NOT EXISTS fact_prices (
    ticker VARCHAR,
    date DATE,
    adj_close DOUBLE,
    is_proxy BOOLEAN,
    PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS dim_client (
    client_id VARCHAR PRIMARY KEY,
    name VARCHAR,
    profile_expected INTEGER
);
CREATE TABLE IF NOT EXISTS fact_goals (
    client_id VARCHAR,
    goal_id VARCHAR,
    bucket_risk INTEGER,
    funding_now DOUBLE,
    monthly_contribution DOUBLE,
    target_nominal DOUBLE,
    date DATE,
    PRIMARY KEY (client_id, goal_id)
);
CREATE TABLE IF NOT EXISTS fact_holdings (
    client_id VARCHAR,
    wrapper VARCHAR,
    ticker VARCHAR,
    units DOUBLE,
    avg_cost DOUBLE,
    as_of DATE,
    PRIMARY KEY (client_id, wrapper, ticker, as_of)
);
CREATE TABLE IF NOT EXISTS fact_proposals (
    client_id VARCHAR,
    created_at TIMESTAMP,
    payload_json VARCHAR,
    PRIMARY KEY (client_id, created_at)
);
CREATE TABLE IF NOT EXISTS fact_ai_documents (
    client_id VARCHAR,
    doc_type VARCHAR,
    lang VARCHAR,
    cache_key VARCHAR,
    text VARCHAR,
    created_at TIMESTAMP,
    PRIMARY KEY (client_id, doc_type, lang, cache_key)
);

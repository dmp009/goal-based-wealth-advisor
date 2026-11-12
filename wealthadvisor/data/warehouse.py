"""DuckDB connection, schema creation, whitelisted upserts and typed readers."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

_SCHEMA = Path(__file__).parent / "schema.sql"

NATURAL_KEYS: dict[str, list[str]] = {
    "dim_product": ["ticker"],
    "fact_prices": ["ticker", "date"],
    "dim_client": ["client_id"],
    "fact_goals": ["client_id", "goal_id"],
    "fact_holdings": ["client_id", "wrapper", "ticker", "as_of"],
    "fact_proposals": ["client_id", "created_at"],
    "fact_ai_documents": ["client_id", "doc_type", "lang", "cache_key"],
}
TABLES = list(NATURAL_KEYS)


def connect(path: Path | str = "data/warehouse.duckdb") -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(_SCHEMA.read_text())
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """Delete rows matching the incoming natural keys, then insert df. Returns rows written."""
    if table not in NATURAL_KEYS:
        raise ValueError(f"Unknown table '{table}'")
    if df.empty:
        return 0
    keys = NATURAL_KEYS[table]
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    missing = set(cols) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns for {table}: {sorted(missing)}")
    data = df[cols]
    con.register("_incoming", data)
    try:
        con.execute("BEGIN")
        cond = " AND ".join(f"t.{k} IS NOT DISTINCT FROM i.{k}" for k in keys)
        con.execute(
            f"DELETE FROM {table} AS t WHERE EXISTS "
            f"(SELECT 1 FROM (SELECT DISTINCT {', '.join(keys)} FROM _incoming) i WHERE {cond})"
        )
        con.execute(f"INSERT INTO {table} SELECT * FROM _incoming")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_incoming")
    return len(data)


def monthly_returns(
    con: duckdb.DuckDBPyConnection, tickers: list[str], start: str | None = None
) -> pd.DataFrame:
    """Simple monthly returns, one column per ticker, indexed by month-end date.

    ``start`` keeps only returns dated on or after it. A ticker's NaNs before its first price
    are left in place (no cross-ticker truncation).
    """
    df = con.execute(
        "SELECT ticker, date, adj_close FROM fact_prices WHERE ticker IN "
        f"({', '.join('?' * len(tickers))}) ORDER BY date",
        list(tickers),
    ).df()
    px = df.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    px.index = pd.to_datetime(px.index)
    px = px.reindex(columns=[t for t in tickers if t in px.columns])
    rets = px.pct_change(fill_method=None).iloc[1:]
    if start is not None:
        rets = rets[rets.index >= pd.Timestamp(start)]
    return rets

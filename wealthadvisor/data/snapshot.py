"""Parquet snapshot of the warehouse, so the app runs without network or a warehouse file."""

from __future__ import annotations

from pathlib import Path

import duckdb

from wealthadvisor.config import REPO_ROOT
from wealthadvisor.data.warehouse import TABLES, connect

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshot"


def _sql_path(p: Path) -> str:
    return p.as_posix().replace("'", "''")


def export_snapshot(con: duckdb.DuckDBPyConnection, out_dir: Path | str = SNAPSHOT_DIR) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        con.execute(
            f"COPY (SELECT * FROM {table}) TO '{_sql_path(out_dir / f'{table}.parquet')}' "
            "(FORMAT PARQUET)"
        )


def load_snapshot(dir: Path | str = SNAPSHOT_DIR) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with every warehouse table loaded from the parquet snapshot."""
    con = connect(":memory:")
    for table in TABLES:
        con.execute(
            f"INSERT INTO {table} SELECT * FROM read_parquet('{_sql_path(Path(dir) / f'{table}.parquet')}')"
        )
    return con

"""Pipeline entry point: ``python -m wealthadvisor.pipeline <command>``."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from wealthadvisor.config import REPO_ROOT, load_etfs
from wealthadvisor.data.ingest import backfill_with_proxy, fetch_monthly
from wealthadvisor.data.quality import run_quality_checks, write_quality_report
from wealthadvisor.data.snapshot import SNAPSHOT_DIR, export_snapshot
from wealthadvisor.data.warehouse import connect, upsert

logger = logging.getLogger(__name__)
BENCHMARK = "^STOXX50E"


def ingest(db_path: Path | str, snapshot_dir: Path | str, report_path: Path | str) -> None:
    etfs = load_etfs()
    con = connect(db_path)
    raw = {t: fetch_monthly(t) for t in [e.ticker for e in etfs] + [BENCHMARK]}

    upsert(
        con,
        "dim_product",
        pd.DataFrame(
            [
                {
                    "ticker": e.ticker,
                    "isin": e.isin,
                    "name": e.name,
                    "asset_class": e.asset_class,
                    "pea_eligible": e.pea_eligible,
                    "sri": e.sri,
                    "ter": e.ter,
                }
                for e in etfs
            ]
        ),
    )
    frames = []
    for e in etfs:
        series = raw[e.ticker]
        flags = pd.Series(False, index=series.index)
        if e.proxy:
            series, flags = backfill_with_proxy(series, raw[e.proxy])
        else:
            logger.info("%s: no proxy, keeping own history", e.ticker)
        frames.append(_to_rows(e.ticker, series, flags))
    bench = raw[BENCHMARK]
    frames.append(_to_rows(BENCHMARK, bench, pd.Series(False, index=bench.index)))
    prices = pd.concat(frames, ignore_index=True)
    upsert(con, "fact_prices", prices)

    for t, g in prices.groupby("ticker"):
        logger.info(
            "%s: first %s, %d months, %d proxy",
            t,
            g["date"].min().date(),
            len(g),
            int(g["is_proxy"].sum()),
        )
    issues = run_quality_checks(con)
    write_quality_report(issues, report_path)
    export_snapshot(con, snapshot_dir)
    logger.info("Ingest done: %d quality issue(s)", len(issues))


def _to_rows(ticker: str, series: pd.Series, flags: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": series.index,
            "adj_close": series.to_numpy(dtype=float),
            "is_proxy": flags.reindex(series.index).to_numpy(dtype=bool),
        }
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wealthadvisor.pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest", help="fetch prices, back-fill, load warehouse, export snapshot")
    p.add_argument("--db", default=REPO_ROOT / "data" / "warehouse.duckdb")
    p.add_argument("--snapshot-dir", default=SNAPSHOT_DIR)
    p.add_argument("--report", default=REPO_ROOT / "data_quality_report.md")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "ingest":
        ingest(args.db, args.snapshot_dir, args.report)


if __name__ == "__main__":
    main()

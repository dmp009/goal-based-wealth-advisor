"""Data-quality checks over the warehouse. Failures are reported, never silently passed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd

from wealthadvisor.config import load_etfs, load_rates
from wealthadvisor.data.warehouse import TABLES

STALE_RUN = 3  # this many identical consecutive month-end closes or more -> warning
CHECKS = (
    ("price_gap", "error", "more than one month between two consecutive prices of a ticker"),
    ("non_positive_price", "error", "missing, zero or negative adjusted close"),
    (
        "stale_price",
        "warning",
        f"{STALE_RUN} or more consecutive identical month-end closes (stale or forward-filled)",
    ),
    ("etf_without_prices", "error", "ETF of the configured universe with no price rows"),
    ("pea_holding_not_eligible", "error", "PEA holding whose product is not PEA-eligible"),
    ("livret_a_over_cap", "error", "Livret A balance above the regulatory ceiling"),
)


@dataclass
class QualityIssue:
    check: str
    ticker: str | None
    detail: str
    severity: Literal["error", "warning"]


def run_quality_checks(con: duckdb.DuckDBPyConnection) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    prices = con.execute(
        "SELECT ticker, date, adj_close FROM fact_prices ORDER BY ticker, date"
    ).df()

    # gap > 1 month inside each ticker's own history
    for ticker, g in prices.groupby("ticker"):
        d = pd.to_datetime(g["date"])
        step = (d.dt.year * 12 + d.dt.month).diff().dropna()
        for idx in step[step > 1].index:
            issues.append(
                QualityIssue(
                    "price_gap",
                    ticker,
                    f"{int(step.loc[idx]) - 1} month(s) missing before {g.loc[idx, 'date']}",
                    "error",
                )
            )

    # stale prices: runs of identical consecutive month-end closes
    for ticker, g in prices.groupby("ticker"):
        px = g["adj_close"].reset_index(drop=True)
        run_id = (px != px.shift()).cumsum()
        for _, run in px.groupby(run_id):
            if len(run) >= STALE_RUN and pd.notna(run.iloc[0]):
                first = g["date"].iloc[run.index[0]]
                last = g["date"].iloc[run.index[-1]]
                issues.append(
                    QualityIssue(
                        "stale_price",
                        ticker,
                        f"{len(run)} identical month-end closes ({run.iloc[0]:g}) "
                        f"from {pd.Timestamp(first).date()} to {pd.Timestamp(last).date()}",
                        "warning",
                    )
                )

    for r in prices[prices["adj_close"].isna() | (prices["adj_close"] <= 0)].itertuples():
        issues.append(
            QualityIssue(
                "non_positive_price", r.ticker, f"{r.date}: adj_close={r.adj_close}", "error"
            )
        )

    have = set(prices["ticker"])
    for etf in load_etfs():
        if etf.ticker not in have:
            issues.append(
                QualityIssue("etf_without_prices", etf.ticker, "no rows in fact_prices", "error")
            )

    # PEA holdings must be PEA-eligible; unknown (None) counts as not eligible (ruling R5)
    bad = con.execute(
        "SELECT DISTINCT h.client_id, h.ticker, p.pea_eligible FROM fact_holdings h "
        "LEFT JOIN dim_product p USING (ticker) "
        "WHERE upper(h.wrapper) = 'PEA' AND p.pea_eligible IS DISTINCT FROM TRUE"
    ).fetchall()
    for client, ticker, flag in bad:
        why = (
            "unknown product"
            if flag is None and not _known(con, ticker)
            else f"pea_eligible={flag}"
        )
        issues.append(
            QualityIssue(
                "pea_holding_not_eligible", ticker, f"client {client}: PEA holding, {why}", "error"
            )
        )

    cap = float(load_rates()["livret_a_cap"]["value"])
    for client, bal in con.execute(
        "SELECT client_id, sum(units * avg_cost) FROM fact_holdings "
        "WHERE lower(wrapper) = 'livret_a' GROUP BY client_id"
    ).fetchall():
        if bal > cap:
            issues.append(
                QualityIssue(
                    "livret_a_over_cap",
                    None,
                    f"client {client}: balance {bal:,.0f} > cap {cap:,.0f}",
                    "error",
                )
            )
    return issues


def _known(con: duckdb.DuckDBPyConnection, ticker: str) -> bool:
    return (
        con.execute("SELECT count(*) FROM dim_product WHERE ticker = ?", [ticker]).fetchone()[0] > 0
    )


def write_quality_report(
    issues: list[QualityIssue],
    path: Path | str = "data_quality_report.md",
    con: duckdb.DuckDBPyConnection | None = None,
) -> None:
    """Markdown report: result, checks run and, given ``con``, row counts and proxy shares."""
    lines = ["# Data quality report", ""]
    if not issues:
        lines.append("No issues found.")
    else:
        errors = sum(i.severity == "error" for i in issues)
        lines += [f"{errors} error(s), {len(issues) - errors} warning(s).", ""]
        lines += ["| Severity | Check | Ticker | Detail |", "|---|---|---|---|"]
        for i in sorted(issues, key=lambda x: (x.severity != "error", x.check)):
            detail = i.detail.replace("|", "\\|")
            lines.append(f"| {i.severity} | {i.check} | {i.ticker or '-'} | {detail} |")
    lines += ["", "## Checks run", "", "| Check | Severity | What it detects |", "|---|---|---|"]
    lines += [f"| `{c}` | {sev} | {what} |" for c, sev, what in CHECKS]
    if con is not None:
        lines += [
            "",
            "## Row counts",
            "",
            "Client tables can be empty: the app reads the sample clients from `data/clients/`.",
            "",
            "| Table | Rows |",
            "|---|---|",
        ]
        for table in TABLES:
            n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            lines.append(f"| {table} | {n} |")
        lines += [
            "",
            "## Proxy share per ticker",
            "",
            "Months back-filled from a proxy index or ETF before the ETF's own history starts.",
            "",
            "| Ticker | Months | Proxy months | Proxy share |",
            "|---|---|---|---|",
        ]
        rows = con.execute(
            "SELECT ticker, count(*), sum(CASE WHEN is_proxy THEN 1 ELSE 0 END) "
            "FROM fact_prices GROUP BY ticker ORDER BY ticker"
        ).fetchall()
        for ticker, n, proxy in rows:
            lines.append(f"| {ticker} | {n} | {int(proxy)} | {100 * proxy / n:.1f}% |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

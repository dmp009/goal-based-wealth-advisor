"""Data-quality checks over the warehouse. Failures are reported, never silently passed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd

from wealthadvisor.config import load_etfs, load_rates


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
    issues: list[QualityIssue], path: Path | str = "data_quality_report.md"
) -> None:
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
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

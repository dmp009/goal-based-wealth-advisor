from pathlib import Path

import pandas as pd
import pytest

from wealthadvisor.data.ingest import backfill_with_proxy
from wealthadvisor.data.quality import run_quality_checks, write_quality_report
from wealthadvisor.data.snapshot import export_snapshot, load_snapshot
from wealthadvisor.data.warehouse import connect, monthly_returns, upsert

FIXTURE = Path(__file__).parent.parent / "fixtures" / "prices_sample.csv"


def _fixture():
    df = pd.read_csv(FIXTURE, parse_dates=["date"], index_col="date")
    return df["etf"].dropna(), df["proxy"]


def test_backfill_chains_proxy_returns():
    etf, proxy = _fixture()
    series, flags = backfill_with_proxy(etf, proxy)
    assert len(series) == 6
    assert series.loc["2020-04-30"] == 50.0  # first ETF price unchanged
    # proxy 99 -> 108.9 is +10%, so the back-filled March price is 50 / 1.1
    assert series.loc["2020-03-31"] == pytest.approx(50 / 1.1)
    assert series.loc["2020-02-29"] == pytest.approx(50 / 1.1 / (99 / 110))
    assert series.loc["2020-01-31"] == pytest.approx(50 / 1.1 / (99 / 110) / 1.1)
    assert list(flags) == [True, True, True, False, False, False]
    assert flags.dtype == bool
    assert series.loc["2020-06-30"] == 52.25  # ETF's own prices untouched


def test_backfill_proxy_not_longer_keeps_etf():
    etf, proxy = _fixture()
    series, flags = backfill_with_proxy(etf, proxy.loc["2020-04-30":])
    assert len(series) == 3 and not flags.any()


def _con_with_prices(rows):
    con = connect(":memory:")
    upsert(
        con, "fact_prices", pd.DataFrame(rows, columns=["ticker", "date", "adj_close", "is_proxy"])
    )
    return con


def test_quality_flags_gap_and_negative_price():
    d = pd.Timestamp
    con = _con_with_prices(
        [
            ("AAA", d("2020-01-31"), 10.0, False),
            ("AAA", d("2020-02-29"), 11.0, False),
            ("AAA", d("2020-05-31"), 12.0, False),  # 3-month jump: months missing
            ("BBB", d("2020-01-31"), 10.0, False),
            ("BBB", d("2020-02-29"), -1.0, False),
        ]
    )
    checks = {(i.check, i.ticker) for i in run_quality_checks(con)}
    assert ("price_gap", "AAA") in checks
    assert ("non_positive_price", "BBB") in checks


def test_quality_holdings_and_livret_cap():
    con = connect(":memory:")
    upsert(
        con,
        "dim_product",
        pd.DataFrame(
            [
                {
                    "ticker": "OK.PA",
                    "isin": None,
                    "name": "ok",
                    "asset_class": "eq",
                    "pea_eligible": True,
                    "sri": 4,
                    "ter": 0.001,
                },
                {
                    "ticker": "UNK.PA",
                    "isin": None,
                    "name": "unk",
                    "asset_class": "eq",
                    "pea_eligible": None,
                    "sri": 4,
                    "ter": 0.001,
                },
            ]
        ),
    )
    upsert(
        con,
        "fact_holdings",
        pd.DataFrame(
            [
                ("c1", "PEA", "OK.PA", 1.0, 10.0, pd.Timestamp("2026-01-01")),
                ("c1", "PEA", "UNK.PA", 1.0, 10.0, pd.Timestamp("2026-01-01")),
                ("c2", "livret_a", "LIVRET_A", 30000.0, 1.0, pd.Timestamp("2026-01-01")),
            ],
            columns=["client_id", "wrapper", "ticker", "units", "avg_cost", "as_of"],
        ),
    )
    issues = run_quality_checks(con)
    names = {(i.check, i.ticker) for i in issues}
    assert ("pea_holding_not_eligible", "UNK.PA") in names
    assert ("pea_holding_not_eligible", "OK.PA") not in names
    assert any(i.check == "livret_a_over_cap" for i in issues)


def test_quality_config_etf_without_prices():
    con = connect(":memory:")
    issues = run_quality_checks(con)
    assert any(i.check == "etf_without_prices" and i.ticker == "CW8.PA" for i in issues)


def test_write_report(tmp_path):
    con = _con_with_prices([("AAA", pd.Timestamp("2020-01-31"), -1.0, False)])
    p = tmp_path / "r.md"
    write_quality_report(run_quality_checks(con), p)
    assert "non_positive_price" in p.read_text()


def test_upsert_unknown_table_raises():
    con = connect(":memory:")
    with pytest.raises(ValueError):
        upsert(con, "dim_evil; DROP TABLE x", pd.DataFrame({"a": [1]}))


def test_upsert_is_idempotent_and_monthly_returns():
    d = pd.Timestamp
    rows = [
        ("AAA", d("2020-01-31"), 100.0, False),
        ("AAA", d("2020-02-29"), 110.0, False),
        ("AAA", d("2020-03-31"), 121.0, False),
    ]
    con = _con_with_prices(rows)
    upsert(
        con, "fact_prices", pd.DataFrame(rows, columns=["ticker", "date", "adj_close", "is_proxy"])
    )
    assert con.execute("SELECT count(*) FROM fact_prices").fetchone()[0] == 3
    r = monthly_returns(con, ["AAA"])
    assert r["AAA"].tolist() == pytest.approx([0.1, 0.1])
    assert len(monthly_returns(con, ["AAA"], start="2020-03-01")) == 1


def test_snapshot_round_trip(tmp_path):
    d = pd.Timestamp
    con = _con_with_prices([("AAA", d("2020-01-31"), 100.0, True)])
    upsert(
        con,
        "fact_proposals",
        pd.DataFrame([{"client_id": "c1", "created_at": d("2026-01-01"), "payload_json": "{}"}]),
    )
    export_snapshot(con, tmp_path)
    con2 = load_snapshot(tmp_path)
    assert con2.execute("SELECT ticker, adj_close, is_proxy FROM fact_prices").fetchall() == [
        ("AAA", 100.0, True)
    ]
    assert con2.execute("SELECT payload_json FROM fact_proposals").fetchone()[0] == "{}"

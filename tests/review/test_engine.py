from datetime import date

import pandas as pd
import pytest

from wealthadvisor.clients.models import Client, list_sample_clients
from wealthadvisor.config import load_rates, load_settings
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.data.warehouse import connect, upsert
from wealthadvisor.review.engine import (
    build_review,
    derive_holdings,
    portfolio_review,
    reprofile,
    review_facts,
)

CLIENTS = {c.client_id: c for c in list_sample_clients()}
NUMERIC_SUFFIXES = ("_pct", "_eur", "_year", "_count")
MONTHS = ["2024-12-31", "2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30", "2025-05-31"]


def _db(prices: dict[str, list[float]]):
    """In-memory warehouse with month-end prices (one list entry per MONTHS date)."""
    con = connect(":memory:")
    rows = [
        {"ticker": t, "date": pd.Timestamp(d).date(), "adj_close": p, "is_proxy": False}
        for t, ps in prices.items()
        for d, p in zip(MONTHS, ps)
    ]
    upsert(con, "fact_prices", pd.DataFrame(rows))
    return con


def _client(original: dict, saving: float = 0.0, proposal_date=date(2025, 1, 31), **kw) -> Client:
    base = CLIENTS["c2"].model_dump()
    base.update(
        client_id="tst",
        monthly_saving=saving,
        original_proposal=original,
        proposal_date=proposal_date,
        **kw,
    )
    return Client.model_validate(base)


def _by_product(holdings):
    return {(h.wrapper, h.ticker or h.product): h for h in holdings}


# ------------------------------------------------------------------ derive_holdings


def test_units_are_amount_over_price_at_proposal_date():
    con = _db({"CW8.PA": [100, 125, 125, 125, 125, 125], "MTD.PA": [50, 40, 40, 40, 40, 40]})
    # proposal date between month ends: the price on or before it (2024-12-31) is used
    c = _client(
        {"pea": {"CW8.PA": 10000}, "cto": {"MTD.PA": 4000}}, proposal_date=date(2025, 1, 15)
    )
    h = _by_product(derive_holdings(c, con, as_of=date(2025, 1, 15)))
    assert h[("pea", "CW8.PA")].units == pytest.approx(100.0)
    assert h[("pea", "CW8.PA")].avg_cost == pytest.approx(100.0)
    assert h[("pea", "CW8.PA")].product == "etf"
    assert h[("cto", "MTD.PA")].units == pytest.approx(80.0)


def test_contributions_and_weighted_average_cost():
    con = _db({"CW8.PA": [100, 100, 200, 200, 200, 200]})
    c = _client({"cto": {"CW8.PA": 10000}}, saving=1000)
    h = _by_product(derive_holdings(c, con, as_of=date(2025, 2, 28)))
    pos = h[("cto", "CW8.PA")]
    assert pos.units == pytest.approx(105.0)
    assert pos.avg_cost == pytest.approx(11000 / 105)


def test_cash_accrues_and_livret_a_overflow_goes_to_fonds_euros():
    rates = load_rates()
    cap = rates["livret_a_cap"]["value"]
    con = _db({"CW8.PA": [100] * 6})
    c = _client({"livret_a": {"livret_a": cap}, "av": {"fonds_euros": 10000}}, saving=1000)
    h = _by_product(derive_holdings(c, con, as_of=date(2025, 2, 28)))
    la_m = (1 + rates["livret_a_rate"]["value"]) ** (1 / 12)
    fe_m = (1 + rates["fonds_euros"]["value"]) ** (1 / 12)
    assert h[("livret_a", "livret_a")].units == pytest.approx(cap * la_m)
    assert h[("av", "fonds_euros")].units == pytest.approx(10000 * fe_m + 1000)
    assert h[("av", "fonds_euros")].ticker is None


def test_structured_held_at_par():
    con = _db({"CW8.PA": [100, 100, 150, 150, 150, 150]})
    c = _client({"av": {"CW8.PA": 6000, "structured:autocall_sx5e": 4000}}, saving=500)
    h = _by_product(derive_holdings(c, con, as_of=date(2025, 3, 31)))
    s = h[("av", "structured:autocall_sx5e")]
    assert s.units * s.avg_cost == pytest.approx(4000)
    # monthly saving does not buy more of the note: all of it goes to the ETF
    assert h[("av", "CW8.PA")].units == pytest.approx(60 + 500 / 150 * 2)


# ------------------------------------------------------------------ performance


def test_twr_zero_for_constant_prices_with_contributions():
    con = _db({"CW8.PA": [100] * 6, "MTD.PA": [80] * 6})
    c = _client({"pea": {"CW8.PA": 10000}, "cto": {"MTD.PA": 5000}}, saving=600)
    perf, _, _, _ = portfolio_review(c, con, as_of=date(2025, 5, 31))
    for key in ("pea", "cto", "total"):
        assert perf[key]["twr"] == pytest.approx(0.0, abs=1e-12)
        assert perf[key]["gain_eur"] == pytest.approx(0.0, abs=1e-6)
    assert perf["total"]["contributed_eur"] == pytest.approx(15000 + 600 * 4)


def test_twr_ignores_contributions():
    con = _db({"CW8.PA": [100, 100, 110, 110, 121, 121]})
    c = _client({"pea": {"CW8.PA": 10000}}, saving=5000)
    perf, _, _, _ = portfolio_review(c, con, as_of=date(2025, 5, 31))
    assert perf["pea"]["twr"] == pytest.approx(0.21)
    assert perf["total"]["twr"] == pytest.approx(0.21)
    value = (100 + 5000 / 110 * 2 + 5000 / 121 * 2) * 121
    assert perf["pea"]["gain_eur"] == pytest.approx(value - 30000)


# ------------------------------------------------------------------ drift and trades


def test_ten_point_drift_in_cto_sells_overweight_buys_underweight_with_tax():
    con = _db({"CW8.PA": [100, 100, 150, 150, 150, 150], "MTD.PA": [50] * 6})
    c = _client({"cto": {"CW8.PA": 50000, "MTD.PA": 50000}})
    _, drift, trades, _ = portfolio_review(c, con, as_of=date(2025, 2, 28))
    assert drift.loc["equity_world", "target"] == pytest.approx(0.5)
    assert drift.loc["equity_world", "current"] == pytest.approx(0.6)
    assert drift.loc["equity_world", "diff"] == pytest.approx(0.1)
    assert drift.loc["bond_gov_euro", "diff"] == pytest.approx(-0.1)
    sells = [t for t in trades if t.action == "sell"]
    buys = [t for t in trades if t.action == "buy"]
    assert [(t.wrapper, t.product) for t in sells] == [("cto", "CW8.PA")]
    assert [(t.wrapper, t.product) for t in buys] == [("cto", "MTD.PA")]
    assert sells[0].amount_eur == pytest.approx(12500)
    assert sum(t.amount_eur for t in buys) == pytest.approx(sum(t.amount_eur for t in sells), abs=1)
    gain = 12500 - 12500 / 150 * 100  # sold units at the weighted average cost
    assert sells[0].taxable and sells[0].est_tax_eur == pytest.approx(0.30 * gain)
    assert not buys[0].taxable and buys[0].est_tax_eur == 0


def test_pea_sell_is_not_taxable():
    con = _db({"CW8.PA": [100, 100, 150, 150, 150, 150], "PCEU.PA": [50] * 6})
    c = _client({"pea": {"CW8.PA": 50000, "PCEU.PA": 50000}})
    _, _, trades, _ = portfolio_review(c, con, as_of=date(2025, 2, 28))
    assert {t.action for t in trades} == {"buy", "sell"}
    assert all(not t.taxable and t.est_tax_eur == 0 for t in trades)


def test_no_trades_inside_band():
    con = _db({"CW8.PA": [100, 100, 105, 105, 105, 105], "MTD.PA": [50] * 6})
    c = _client({"cto": {"CW8.PA": 50000, "MTD.PA": 50000}})
    _, drift, trades, _ = portfolio_review(c, con, as_of=date(2025, 2, 28))
    assert abs(drift.loc["equity_world", "diff"]) < load_settings().drift_band
    assert trades == []


def test_no_money_moves_between_wrappers():
    # each wrapper holds one class: the overall drift cannot be fixed inside a wrapper
    con = _db({"CW8.PA": [100, 100, 150, 150, 150, 150], "MTD.PA": [50] * 6})
    c = _client({"pea": {"CW8.PA": 50000}, "av": {"MTD.PA": 50000}})
    _, drift, trades, _ = portfolio_review(c, con, as_of=date(2025, 2, 28))
    assert drift.loc["equity_world", "diff"] == pytest.approx(0.1)
    assert trades == []


# ------------------------------------------------------------------ re-profile


def test_profile_change_flagged_when_answers_change():
    c = CLIENTS["c2"]
    before, now, changed = reprofile(c, date(2025, 4, 30), date(2026, 10, 31))
    assert before == 4 and now.profile == 4 and not changed
    cautious = {
        **c.answers,
        "risk_reaction": "sell_all",
        "risk_tradeoff": "capital_safe",
        "objective": "capital_preservation",
        "loss_capacity": "low",
    }
    before, now, changed = reprofile(c, date(2025, 4, 30), date(2026, 10, 31), cautious)
    assert before == 4 and now.profile < 4 and changed


def test_clients_without_portfolio_raise():
    con = _db({"CW8.PA": [100] * 6})
    for cid in ("c1", "c4"):
        with pytest.raises(ValueError, match="Client has no existing portfolio"):
            build_review(CLIENTS[cid], con)


# ------------------------------------------------------------------ real snapshot


@pytest.fixture(scope="module")
def snap():
    return load_snapshot()


@pytest.fixture(scope="module")
def reviews(snap):
    return {cid: build_review(CLIENTS[cid], snap) for cid in ("c2", "c3")}


def test_c2_c3_reviews_build(reviews):
    for cid, r in reviews.items():
        c = CLIENTS[cid]
        assert r.client_id == cid and r.as_of == date(2026, 10, 31)
        assert r.proposal_date == date(2025, 4, 30)
        assert "total" in r.performance
        assert -0.5 < r.performance["total"]["twr"] < 1.0
        assert r.performance["total"]["contributed_eur"] == pytest.approx(
            sum(sum(p.values()) for p in c.original_proposal.values()) + 18 * c.monthly_saving
        )
        assert list(r.drift.columns) == ["target", "current", "diff"]
        assert r.drift["target"].sum() == pytest.approx(1.0)
        assert r.drift["current"].sum() == pytest.approx(1.0)
        assert not r.profile_changed and r.profile_before == r.profile_now.profile
        assert [g.goal_id for g in r.goals_before] == [g.goal_id for g in r.goals_now]
        assert len(r.goals_now) == len(c.goals)
        for g in r.goals_before + r.goals_now:
            assert 0.0 <= g.probability <= 1.0
        for w in {t.wrapper for t in r.trades}:
            buys = sum(t.amount_eur for t in r.trades if t.wrapper == w and t.action == "buy")
            sells = sum(t.amount_eur for t in r.trades if t.wrapper == w and t.action == "sell")
            assert buys == pytest.approx(sells, abs=1)
        for t in r.trades:
            assert t.taxable == (t.wrapper == "cto" and t.action == "sell")
            assert t.amount_eur > 0


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, path)
    else:
        yield path, obj


def test_review_facts_naming(reviews):
    s = load_settings()
    for r in reviews.values():
        f = review_facts(r)
        assert f["disclaimer"] == s.disclaimer
        assert f["profile"]["profile_before_count"] == r.profile_before
        g = f["goals"][0]
        for key in ("label", "label_fr", "probability_before_pct", "probability_now_pct"):
            assert key in g
        assert f["performance"]["total"]["twr_pct"] == round(r.performance["total"]["twr"] * 100, 1)
        assert {"asset_class", "target_pct", "current_pct", "diff_pct"} <= set(f["drift"][0])
        for k, v in _walk(f):
            if isinstance(v, bool) or not isinstance(v, int | float):
                continue
            assert k == "age" or k.endswith(NUMERIC_SUFFIXES), k
            if k.endswith("_pct"):
                assert round(v, 1) == v
            if k.endswith(("_eur", "_year", "_count")) or k == "age":
                assert isinstance(v, int), (k, v)


def test_prices_until_limits_history(snap):
    from wealthadvisor.proposal import prices_until, snapshot_today

    limited = prices_until(snap, date(2025, 4, 30))
    assert snapshot_today(limited) == date(2025, 4, 30)
    assert snapshot_today(snap) == date(2026, 10, 31)

import numpy as np
import pandas as pd
import pytest

from wealthadvisor.config import (
    ETF,
    ProfileRule,
    load_cma,
    load_etfs,
    load_profiles,
)
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.data.warehouse import monthly_returns
from wealthadvisor.portfolio.optimise import optimise
from wealthadvisor.portfolio.riskmodel import (
    covariance,
    expected_returns,
    portfolio_stats,
)

METHODS = ["markowitz", "black_litterman", "hrp"]
TICKERS = ["EQ1", "EQ2", "BD1", "BD2"]


def _etf(t, ac):
    return ETF(ticker=t, isin=None, name=t, asset_class=ac, pea_eligible=None, sri=None, ter=None)


ETFS = [
    _etf("EQ1", "equity_world"),
    _etf("EQ2", "equity_em"),
    _etf("BD1", "bond_gov_euro"),
    _etf("BD2", "bond_corp_euro"),
]
CMA = {
    "equity_world": 0.065,
    "equity_em": 0.078,
    "bond_gov_euro": 0.03,
    "bond_corp_euro": 0.037,
}


@pytest.fixture
def rets():
    rng = np.random.default_rng(0)
    n = 120
    f = rng.normal(0.005, 0.04, n)
    data = {
        "EQ1": f + rng.normal(0, 0.01, n),
        "EQ2": 1.2 * f + rng.normal(0, 0.02, n),
        "BD1": rng.normal(0.002, 0.012, n),
        "BD2": 0.3 * f + rng.normal(0.003, 0.015, n),
    }
    idx = pd.date_range("2015-01-31", periods=n, freq="ME")
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def setup(rets):
    cov = covariance(rets)
    mu = expected_returns(TICKERS, ETFS, CMA)
    return mu, cov


RULE = ProfileRule(profile=4, vol_cap=0.06, max_equity=0.6, min_safe_share=0.25)


def _eq_share(w):
    return float(w[[t for t in w.index if t.startswith("EQ")]].sum())


def test_covariance_annualised_psd(rets):
    cov = covariance(rets)
    assert list(cov.columns) == TICKERS
    assert np.allclose(cov, cov.T)
    assert np.linalg.eigvalsh(cov.values).min() > 0
    raw = rets.cov() * 12
    assert (
        abs(cov.values.diagonal() - raw.values.diagonal()).max() < 0.2 * raw.values.diagonal().max()
    )


def test_covariance_requires_36_months(rets):
    with pytest.raises(ValueError):
        covariance(rets.iloc[:35])
    r = rets.copy()
    r.iloc[:90, 0] = np.nan  # common window only 30 rows
    with pytest.raises(ValueError):
        covariance(r)


def test_expected_returns():
    mu = expected_returns(["BD2", "EQ1"], ETFS, CMA)
    assert mu["BD2"] == 0.037 and mu["EQ1"] == 0.065


def test_portfolio_stats_sleeve_and_bucket(setup):
    mu, cov = setup
    w = pd.Series([0.25] * 4, index=TICKERS)
    sleeve = portfolio_stats(w, mu, cov, 0.0, 0.02)
    assert sleeve["expected_return"] == pytest.approx(float(w @ mu))
    assert sleeve["volatility"] == pytest.approx(float(np.sqrt(w @ cov @ w)))
    bucket = portfolio_stats(w, mu, cov, 0.25, 0.02)
    assert bucket["expected_return"] == pytest.approx(0.75 * float(w @ mu) + 0.25 * 0.02)
    assert bucket["volatility"] == pytest.approx(0.75 * sleeve["volatility"])


@pytest.mark.parametrize("method", METHODS)
def test_optimise_valid_and_capped(method, setup, rets):
    mu, cov = setup
    safe = 0.25
    cap = RULE.vol_cap / (1 - safe)
    res = optimise(method, TICKERS, mu, cov, rets, RULE, safe, 0.8, etfs=ETFS)
    w = res.weights
    assert res.method == method
    assert w.sum() == pytest.approx(1.0)
    assert (w >= 0).all()
    assert res.volatility <= cap + 1e-6
    assert _eq_share(w) <= 0.8 + 1e-6
    assert res.expected_return == pytest.approx(float(w @ mu))
    assert -1 < res.max_drawdown < 0
    assert res.notes == []


@pytest.mark.parametrize("method", METHODS)
def test_equity_cap_binding(method, setup, rets):
    mu, cov = setup
    res = optimise(method, TICKERS, mu, cov, rets, RULE, 0.0, 0.2, etfs=ETFS)
    assert _eq_share(res.weights) <= 0.2 + 1e-6
    assert res.weights.sum() == pytest.approx(1.0)


@pytest.mark.parametrize("method", METHODS)
def test_safe_share_one_gives_empty(method, setup, rets):
    mu, cov = setup
    res = optimise(method, TICKERS, mu, cov, rets, RULE, 1.0, 0.0, etfs=ETFS)
    assert res.weights.empty
    assert res.expected_return == 0 and res.volatility == 0 and res.max_drawdown == 0
    assert "No risky sleeve: bucket fully in safe assets." in res.notes


@pytest.mark.parametrize("method", METHODS)
def test_infeasible_vol_cap_falls_back(method, setup, rets):
    mu, cov = setup
    tight = ProfileRule(profile=1, vol_cap=0.001, max_equity=0.0, min_safe_share=0.8)
    res = optimise(method, TICKERS, mu, cov, rets, tight, 0.0, 0.0, etfs=ETFS)
    assert res.weights.sum() == pytest.approx(1.0)
    assert _eq_share(res.weights) <= 1e-6
    assert res.notes and all(isinstance(n, str) for n in res.notes)


@pytest.mark.parametrize("method", METHODS)
def test_no_non_equity_and_cap_below_one(method, rets):
    t = ["EQ1", "EQ2"]
    cov = covariance(rets[t])
    mu = expected_returns(t, ETFS, CMA)
    res = optimise(method, t, mu, cov, rets[t], RULE, 0.0, 0.5, etfs=ETFS)
    assert res.weights.sum() == pytest.approx(1.0)
    assert res.notes


def test_bl_views_shift_weights(setup, rets):
    mu, cov = setup
    loose = ProfileRule(profile=7, vol_cap=0.07, max_equity=1.0, min_safe_share=0.0)
    base = optimise("black_litterman", TICKERS, mu, cov, rets, loose, 0.0, 1.0, etfs=ETFS)
    view = optimise(
        "black_litterman",
        TICKERS,
        mu,
        cov,
        rets,
        loose,
        0.0,
        1.0,
        views={"equity_em": 0.20},
        etfs=ETFS,
    )
    assert view.weights["EQ2"] > base.weights["EQ2"]


def test_same_mu_for_stats_across_methods(setup, rets):
    mu, cov = setup
    for m in METHODS:
        r = optimise(m, TICKERS, mu, cov, rets, RULE, 0.0, 1.0, etfs=ETFS)
        assert r.expected_return == pytest.approx(float(r.weights @ mu))


def test_smoke_real_snapshot_all_methods():
    etfs = load_etfs()
    tickers = [e.ticker for e in etfs]
    con = load_snapshot()
    rets = monthly_returns(con, tickers)
    cma = load_cma()
    cov = covariance(rets)
    mu = expected_returns(tickers, etfs, cma)
    rule = load_profiles()[4]
    safe = 0.25
    cap = rule.vol_cap / (1 - safe)
    mes = min(1.0, rule.max_equity / (1 - safe))
    for m in METHODS:
        r = optimise(m, tickers, mu, cov, rets, rule, safe, mes, etfs=etfs)
        assert r.weights.sum() == pytest.approx(1.0)
        assert (r.weights >= 0).all()
        assert r.volatility <= cap + 1e-6, (m, r.volatility, cap)
        eq = sum(
            w
            for t, w in r.weights.items()
            if next(e for e in etfs if e.ticker == t).asset_class.startswith("equity_")
        )
        assert eq <= mes + 1e-6


def test_hrp_in_house_three_assets():
    from wealthadvisor.portfolio.optimise import _hrp_weights

    names = ["A", "B", "C"]
    sd = np.array([0.1, 0.1, 0.1])
    corr = np.array([[1, 0.9, 0.0], [0.9, 1, 0.0], [0.0, 0.0, 1]])
    cov = pd.DataFrame(corr * np.outer(sd, sd), index=names, columns=names)
    w = _hrp_weights(cov)
    assert w.sum() == pytest.approx(1.0)
    assert (w > 0).all()
    assert w["C"] > w["A"] and w["C"] > w["B"]
    assert w["A"] == pytest.approx(w["B"])
    # cluster var of {A,B} = 0.0095, of C = 0.01 -> C weight = 0.0095 / 0.0195
    assert w["C"] == pytest.approx(0.0095 / 0.0195, abs=1e-6)
    assert _hrp_weights(cov.iloc[:1, :1]).iloc[0] == 1.0

from datetime import date

import numpy as np
import pytest

from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.config import load_rates, load_settings
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.structured.payoff import (
    autocall_payoff,
    cpn_payoff,
    historical_sigma,
    simulate_index,
    structured_allocation,
)
from wealthadvisor.suitability.scoring import score_profile
from wealthadvisor.wrappers.allocate import plan_buckets

TODAY = date(2026, 10, 31)
CLIENTS = {c.client_id: c for c in list_sample_clients()}


def path(*lv):
    return np.array([[1.0, *lv]])


def test_autocall_called_year_1():
    r = autocall_payoff(path(1.05, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9), 0.07, 0.6)
    assert r.called_year[0] == 1 and r.payoff_multiple[0] == pytest.approx(1.07)


def test_autocall_loss_and_barrier_and_maturity_coupon():
    lv = [0.9] * 7
    assert autocall_payoff(path(*lv, 0.55), 0.07, 0.6).payoff_multiple[0] == pytest.approx(0.55)
    assert autocall_payoff(path(*lv, 0.70), 0.07, 0.6).payoff_multiple[0] == pytest.approx(1.0)
    r = autocall_payoff(path(*lv, 1.02), 0.07, 0.6)
    assert r.payoff_multiple[0] == pytest.approx(1.56) and r.called_year[0] == 8


def test_autocall_describe_and_prob_loss():
    r = autocall_payoff(np.vstack([path(*[0.9] * 7, 0.55), path(*[0.9] * 7, 0.7)]), 0.07, 0.6)
    assert "unless" in r.describe and "capital protected" not in r.describe.lower()
    assert "40 %" in r.describe
    assert r.prob_capital_loss == 0.5


def test_cpn():
    r = cpn_payoff(path(*[1.0] * 7, 1.2), 0.5)
    assert r.payoff_multiple[0] == pytest.approx(1.10)
    assert cpn_payoff(path(*[1.0] * 7, 0.6), 0.5).payoff_multiple[0] == 1.0
    assert r.prob_capital_loss == 0.0 and "100 %" in r.describe


def test_simulate_shape_and_reproducible():
    a = simulate_index(1.0, 0.05, 0.18, 8, 1000, 42)
    assert a.shape == (1000, 9) and (a[:, 0] == 1).all()
    assert np.array_equal(a, simulate_index(1.0, 0.05, 0.18, 8, 1000, 42))


def _plan(c):
    p = score_profile(c, TODAY)
    return p, plan_buckets(c, p.profile, TODAY, load_rates(), load_settings())


def test_c4_excluded():
    p, bp = _plan(CLIENTS["c4"])
    d = structured_allocation(CLIENTS["c4"], p, bp, TODAY)
    assert not d.included and d.amount == 0 and d.payoff is None and d.reasons


def test_c3_included_capped():
    c = CLIENTS["c3"]
    p, bp = _plan(c)
    d = structured_allocation(c, p, bp, TODAY)
    inv = c.liquid_assets - bp.emergency.funded
    assert d.included and d.product_id == "autocall_sx5e"
    assert 0 < d.amount <= 0.15 * inv + 1e-6
    assert d.wrapper in ("av", "cto") and d.payoff is not None
    pr = d.payoff
    life = np.where(pr.called_year > 0, pr.called_year, 8).mean()
    assert pr.annualised_expected_return == pytest.approx(
        pr.expected_multiple ** (1 / life) - 1, abs=1e-9
    )


def test_annualised_return_hand_built_autocall():
    flat = [0.9] * 7
    levels = np.vstack(
        [
            path(1.05, *[0.9] * 7),  # called y1 -> 1.07
            path(0.9, 0.9, 1.0, *[0.9] * 5),  # called y3 -> 1.21
            path(*flat, 0.70),  # not called, above barrier -> 1.0
            path(*flat, 0.50),  # not called, loss -> 0.5
        ]
    )
    r = autocall_payoff(levels, 0.07, 0.6)
    assert list(r.called_year) == [1, 3, 0, 0]
    assert r.expected_multiple == pytest.approx(0.945, abs=1e-9)
    mean_life = (1 + 3 + 8 + 8) / 4
    assert r.annualised_expected_return == pytest.approx(0.945 ** (1 / mean_life) - 1, abs=1e-9)
    assert r.prob_capital_loss == 0.25


def test_annualised_return_hand_built_cpn():
    levels = np.vstack([path(*[1.0] * 7, f) for f in (1.2, 1.0, 0.6, 1.6)])
    r = cpn_payoff(levels, 0.5)
    assert r.expected_multiple == pytest.approx(1.1, abs=1e-9)
    assert r.annualised_expected_return == pytest.approx(1.1 ** (1 / 8) - 1, abs=1e-9)


def test_real_snapshot_sigma():
    con = load_snapshot()
    s = historical_sigma(con)
    assert 0.10 < s < 0.35
    c = CLIENTS["c3"]
    p, bp = _plan(c)
    assert structured_allocation(c, p, bp, TODAY, con=con).included

import time

import numpy as np
import pandas as pd
import pytest

from wealthadvisor.goals.montecarlo import _after_tax, simulate_bucket
from wealthadvisor.wrappers.allocate import Bucket
from wealthadvisor.wrappers.tax import tax_on_gain


def _bucket(**kw):
    d = {
        "goal_id": "g",
        "horizon_years": 5,
        "risk": 3,
        "funding_now": 10000.0,
        "monthly_contribution": 0.0,
        "target_nominal": 11000.0,
        "wrapper_split": {"cto": 10000.0},
        "safe_share": 0.0,
        "rules": [],
    }
    d.update(kw)
    return Bucket(**d)


def _mk(n=2, vol=0.0):
    t = [f"A{i}" for i in range(n)]
    mu = pd.Series(0.05, index=t)
    cov = pd.DataFrame(np.eye(n) * vol**2, index=t, columns=t)
    w = pd.Series(1.0 / n, index=t)
    return w, mu, cov


def test_deterministic_above_target_prob_one():
    w, mu, cov = _mk()
    # 10000 * 1.05**5 = 12763 pre-tax; gain 2763 * 0.7 -> ~11929 >= 11000
    r = simulate_bucket(_bucket(), w, mu, cov, 0.02, 500, 42, "single")
    assert r.probability == 1.0 and not r.underfunded


def test_deterministic_below_target_prob_zero():
    w, mu, cov = _mk()
    r = simulate_bucket(_bucket(target_nominal=20000.0), w, mu, cov, 0.02, 500, 42, "single")
    assert r.probability == 0.0


def test_same_seed_identical():
    w, mu, cov = _mk(vol=0.15)
    a = simulate_bucket(_bucket(target_nominal=12000.0), w, mu, cov, 0.02, 1000, 7, "single")
    b = simulate_bucket(_bucket(target_nominal=12000.0), w, mu, cov, 0.02, 1000, 7, "single")
    assert a.probability == b.probability and a.p50 == b.p50
    pd.testing.assert_frame_equal(a.paths_quantiles, b.paths_quantiles)


def test_underfunded():
    w, mu, cov = _mk()
    r = simulate_bucket(_bucket(funding_now=0.0), w, mu, cov, 0.02, 100, 1, "single")
    assert r.underfunded and r.probability == 0.0 and r.p10 == r.p50 == r.p90 == 0.0


def test_quantiles_ordered_and_shape():
    w, mu, cov = _mk(vol=0.15)
    r = simulate_bucket(_bucket(monthly_contribution=100.0), w, mu, cov, 0.02, 2000, 3, "single")
    q = r.paths_quantiles
    assert len(q) == 61 and list(q.columns) == ["p10", "p50", "p90"]
    assert (q.p10 <= q.p50).all() and (q.p50 <= q.p90).all()
    assert r.p10 <= r.p50 <= r.p90


def test_fully_safe_bucket():
    r = simulate_bucket(
        _bucket(safe_share=1.0, target_nominal=10500.0),
        pd.Series(dtype=float),
        pd.Series(dtype=float),
        pd.DataFrame(),
        0.02,
        100,
        1,
        "single",
    )
    assert r.probability == 1.0


def test_vectorised_tax_matches_scalar():
    for split, years, hh in [
        ({"av": 1.0, "pea": 1.0, "cto": 1.0, "livret_a": 1.0}, 9, "couple"),
        ({"av": 1.0, "pea": 2.0}, 4, "single"),
    ]:
        final = np.array([-500.0, 0.0, 3000.0, 20000.0, 50000.0])
        contributed = 10000.0
        got = _after_tax(final + contributed, contributed, split, years, hh)
        tot = sum(split.values())
        for i, f in enumerate(final):
            exp = (
                f
                + contributed
                - sum(tax_on_gain(wr, f * v / tot, years, hh) for wr, v in split.items())
            )
            assert got[i] == pytest.approx(exp)


def test_performance_10k_by_240():
    w, mu, cov = _mk(n=14, vol=0.15)
    t0 = time.time()
    simulate_bucket(
        _bucket(horizon_years=20, monthly_contribution=300.0), w, mu, cov, 0.02, 10000, 42, "single"
    )
    assert time.time() - t0 < 5

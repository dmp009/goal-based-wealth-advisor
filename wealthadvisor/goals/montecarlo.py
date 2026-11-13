"""Goal Monte Carlo (design §6.7, §9.1, §9.2).

Performance note: the risky sleeve holds fixed weights, so its monthly return is a linear
combination of jointly normal asset returns, i.e. exactly univariate normal with mean w.mu_m and
variance w' Sigma_m w. We simulate that scalar directly (mathematically equivalent to drawing the
full multivariate vector and projecting, but ~n_assets times cheaper).

Simplifications: monthly return mean is (1+mu)^(1/12)-1 and covariance is cov/12; contributions
arrive at month end with the same safe/risky split as the initial funding; the tax is applied to
the total gain at the goal date, spread across wrappers pro rata to the wrapper split.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from wealthadvisor.config import load_tax_rules
from wealthadvisor.wrappers.allocate import Bucket


@dataclass
class GoalResult:
    goal_id: str
    probability: float
    p10: float
    p50: float
    p90: float
    paths_quantiles: pd.DataFrame
    underfunded: bool


def _tax_array(wrapper: str, gain: np.ndarray, years: float, household: str, r: dict) -> np.ndarray:
    """Vectorised mirror of ``wrappers.tax.tax_on_gain`` (the scalar function is the reference)."""
    g = np.maximum(gain, 0.0)
    if wrapper == "livret_a":
        return g * r["livret_a"]["rate"]
    if wrapper == "pea":
        p = r["pea"]
        return g * (p["rate_after_5y"] if years >= p["threshold_years"] else p["rate_before_5y"])
    if wrapper in ("av", "fonds_euros"):
        a = r["assurance_vie"]
        if years >= a["threshold_years"]:
            allowance = a["allowance_couple" if household == "couple" else "allowance_single"]
            return np.maximum(0.0, g - allowance) * a["rate_after_8y"]
        return g * a["rate_before_8y"]
    if wrapper == "cto":
        return g * r["cto"]["rate"]
    raise ValueError(f"unknown wrapper {wrapper!r}")


def _after_tax(
    final: np.ndarray, contributed: float, split: dict[str, float], years: float, household: str
) -> np.ndarray:
    rules = load_tax_rules()
    split = {k: v for k, v in split.items() if v > 0} or {"av": 1.0}
    total = sum(split.values())
    gain = final - contributed
    tax = np.zeros_like(final)
    for wrapper, amount in split.items():
        tax += _tax_array(wrapper, gain * amount / total, years, household, rules)
    return final - tax


def simulate_bucket(
    bucket: Bucket,
    weights: pd.Series,
    mu: pd.Series,
    cov: pd.DataFrame,
    safe_rate: float,
    n_paths: int,
    seed: int,
    household: str,
) -> GoalResult:
    months = max(1, round(bucket.horizon_years * 12))
    idx = np.arange(months + 1)
    if bucket.funding_now <= 0 and bucket.monthly_contribution <= 0:
        zero = pd.DataFrame(0.0, index=idx, columns=["p10", "p50", "p90"])
        return GoalResult(bucket.goal_id, 0.0, 0.0, 0.0, 0.0, zero, True)

    rng = np.random.default_rng(seed)
    safe_m = (1 + safe_rate) ** (1 / 12) - 1
    safe_share = min(max(bucket.safe_share, 0.0), 1.0)
    if len(weights) == 0:
        safe_share = 1.0
        r_mean, r_std = 0.0, 0.0
    else:
        w = weights.to_numpy(dtype=float)
        mu_m = (1 + mu.reindex(weights.index).to_numpy(dtype=float)) ** (1 / 12) - 1
        sigma_m = cov.loc[weights.index, weights.index].to_numpy(dtype=float) / 12
        r_mean = float(w @ mu_m)
        r_std = float(np.sqrt(max(w @ sigma_m @ w, 0.0)))

    c = bucket.monthly_contribution
    safe = np.full(n_paths, bucket.funding_now * safe_share)
    risky = np.full(n_paths, bucket.funding_now * (1 - safe_share))
    values = np.empty((months + 1, n_paths))
    values[0] = safe + risky
    shocks = rng.standard_normal((months, n_paths))
    for m in range(months):
        safe = safe * (1 + safe_m) + c * safe_share
        risky = risky * (1 + r_mean + r_std * shocks[m]) + c * (1 - safe_share)
        values[m + 1] = safe + risky

    final = values[-1]
    contributed = bucket.funding_now + c * months
    split = bucket.wrapper_split or bucket.monthly_split or {"av": 1.0}
    net = _after_tax(final, contributed, split, bucket.horizon_years, household)
    q = np.percentile(values, [10, 50, 90], axis=1).T
    quantiles = pd.DataFrame(q, index=idx, columns=["p10", "p50", "p90"])
    p10, p50, p90 = (float(x) for x in np.percentile(net, [10, 50, 90]))
    prob = float(np.mean(net >= bucket.target_nominal))
    return GoalResult(bucket.goal_id, prob, p10, p50, p90, quantiles, False)

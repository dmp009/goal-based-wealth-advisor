"""Generic structured-product templates on the Euro Stoxx 50 (design §6.8, §9.1, §9.6).

Documented conventions:
- ``simulate_index`` returns annual GBM levels with shape (n_paths, years + 1); column 0 is s0,
  column k is the level at observation year k.
- Autocall ("Athena" snowball coupon): called at the first observation year k (1..years) where the
  level >= ``autocall_level``; payoff = 1 + coupon * k. Never called: at maturity the payoff is
  1 + coupon * years if level >= autocall_level (i.e. called at maturity), 1.0 if level >= barrier,
  else the final level (capital loss). ``called_year`` is 0 when never called, k otherwise.
- CPN: 100 % of capital at maturity + participation * max(0, index return); called_year = years.
- Product choice: ``autocall_sx5e`` for profile >= 5, else ``cpn_sx5e``.
- Sizing: max_share * investable (liquid assets - funded emergency fund); horizon used is the
  longest bucket horizon; wrapper ``av`` if any bucket uses AV, else ``cto``.
- sigma: stdev of ^STOXX50E monthly returns * sqrt(12) when a connection is given, else 0.18.
- mu = CMA equity_europe - dividend_yield (price index).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import numpy as np

from wealthadvisor.clients.models import Client
from wealthadvisor.config import load_cma, load_settings, load_structured
from wealthadvisor.suitability.products import check_product
from wealthadvisor.suitability.scoring import ProfileResult
from wealthadvisor.wrappers.allocate import BucketPlan

DEFAULT_SIGMA = 0.18
UNDERLYING = "^STOXX50E"


@dataclass
class PayoffResult:
    payoff_multiple: np.ndarray
    called_year: np.ndarray
    prob_capital_loss: float
    expected_multiple: float
    describe: str
    annualised_expected_return: float = 0.0


@dataclass
class StructuredDecision:
    included: bool
    product_id: str | None
    amount: float
    wrapper: Literal["av", "cto"]
    reasons: list[str] = field(default_factory=list)
    payoff: PayoffResult | None = None


def simulate_index(
    s0: float, mu: float, sigma: float, years: int, n_paths: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_paths, years))
    steps = (mu - 0.5 * sigma**2) + sigma * z
    logs = np.cumsum(steps, axis=1)
    return np.hstack([np.full((n_paths, 1), s0), s0 * np.exp(logs)])


def historical_sigma(con) -> float:
    from wealthadvisor.data.warehouse import monthly_returns

    r = monthly_returns(con, [UNDERLYING])[UNDERLYING].dropna()
    return float(r.std(ddof=1) * np.sqrt(12))


def _annualised(multiple: np.ndarray, life: np.ndarray) -> float:
    e = float(multiple.mean())
    return float(e ** (1.0 / float(life.mean())) - 1.0)


def autocall_payoff(
    levels: np.ndarray, coupon: float, barrier: float, autocall_level: float = 1.0
) -> PayoffResult:
    years = levels.shape[1] - 1
    obs = levels[:, 1:]
    hit = obs >= autocall_level
    called = hit.any(axis=1)
    first = np.where(called, hit.argmax(axis=1) + 1, 0)
    final = levels[:, -1]
    pay = np.where(
        called,
        1.0 + coupon * first,
        np.where(final >= barrier, 1.0, final),
    )
    loss = float(np.mean(~called & (final < barrier)))
    life = np.where(called, first, years)
    drop = round((1 - barrier) * 100)
    describe = (
        f"{years}-year autocall on the Euro Stoxx 50: if the index is at or above "
        f"{autocall_level * 100:.0f} % of its start on an annual observation date, the product "
        f"is called early and pays {coupon * 100:.1f} % per elapsed year. Otherwise capital is "
        f"repaid at maturity unless the index has fallen more than {drop} %, in which case the "
        f"investor bears the full index loss. Issuer credit risk applies."
    )
    return PayoffResult(pay, first, loss, float(pay.mean()), describe, _annualised(pay, life))


def cpn_payoff(levels: np.ndarray, participation: float) -> PayoffResult:
    years = levels.shape[1] - 1
    final = levels[:, -1] / levels[:, 0]
    pay = 1.0 + participation * np.maximum(0.0, final - 1.0)
    describe = (
        f"{years}-year note: 100 % of capital repaid at maturity plus {participation * 100:.0f} % "
        f"of any rise in the Euro Stoxx 50 (price index, dividends not included). "
        f"Issuer credit risk applies."
    )
    called = np.full(levels.shape[0], years)
    life = np.full(levels.shape[0], years)
    return PayoffResult(pay, called, 0.0, float(pay.mean()), describe, _annualised(pay, life))


def structured_allocation(
    client: Client, profile: ProfileResult, bucket_plan: BucketPlan, today: date, con=None
) -> StructuredDecision:
    cfg = load_structured()
    horizon = max((b.horizon_years for b in bucket_plan.buckets), default=0.0)
    suit = check_product("structured", client, profile, horizon)
    if not suit.included:
        return StructuredDecision(False, None, 0.0, "cto", list(suit.reasons), None)

    product_id = "autocall_sx5e" if profile.profile >= 5 else "cpn_sx5e"
    tpl = cfg["templates"][product_id]
    investable = max(0.0, client.liquid_assets - bucket_plan.emergency.funded)
    amount = cfg["max_share"] * investable
    uses_av = any(b.wrapper_split.get("av", 0) > 0 for b in bucket_plan.buckets)
    wrapper: Literal["av", "cto"] = "av" if uses_av else "cto"

    settings = load_settings()
    sigma = historical_sigma(con) if con is not None else DEFAULT_SIGMA
    mu = load_cma()["equity_europe"] - cfg["dividend_yield"]
    levels = simulate_index(1.0, mu, sigma, tpl["years"], settings.n_paths, settings.seed)
    if product_id == "autocall_sx5e":
        payoff = autocall_payoff(levels, tpl["coupon"], tpl["barrier"], tpl["autocall_level"])
    else:
        payoff = cpn_payoff(levels, tpl["participation"])
    note = (
        f"Product {product_id} chosen for profile {profile.profile}; amount capped at "
        f"{cfg['max_share'] * 100:.0f} % of investable assets after the emergency fund."
    )
    reasons = [*suit.reasons, note]
    return StructuredDecision(True, product_id, float(amount), wrapper, reasons, payoff)

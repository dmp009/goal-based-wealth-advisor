"""Markowitz, Black-Litterman and HRP optimisers on one shared risk/return model.

``OptResult`` reports SLEEVE-level statistics (the risky sleeve alone, evaluated with the CMA
``mu`` and shared ``cov`` for every method). Use ``riskmodel.portfolio_stats`` for bucket stats.
The caller computes ``max_equity_in_sleeve = min(1, max_equity / (1 - safe_share))``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import cvxpy as cp
import numpy as np
import pandas as pd
from pypfopt import BlackLittermanModel, EfficientFrontier
from pypfopt.exceptions import OptimizationError
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

from wealthadvisor.config import ETF, ProfileRule, load_etfs, load_reference_weights
from wealthadvisor.portfolio.riskmodel import common_window

_SOLVER_ERRORS = (ValueError, OptimizationError, cp.error.SolverError)
DELTA = 2.5
TINY = 1e-4


@dataclass
class OptResult:
    weights: pd.Series
    expected_return: float
    volatility: float
    max_drawdown: float
    method: str
    notes: list[str] = field(default_factory=list)


def _clean(w: pd.Series) -> pd.Series:
    w = w.clip(lower=0.0)
    kept = w.where(w >= TINY, 0.0)
    if kept.sum() <= 0:  # all-tiny vector: keep the raw (clipped) weights rather than divide by 0
        kept = w
    return kept / kept.sum()


def _hrp_weights(cov: pd.DataFrame) -> pd.Series:
    """Hierarchical Risk Parity (Lopez de Prado) from the shared covariance matrix.

    Distance sqrt((1 - corr) / 2), single linkage, quasi-diagonalised leaf order, recursive
    bisection with inverse-variance cluster weights.
    """
    n = len(cov)
    if n == 1:
        return pd.Series(1.0, index=cov.index)
    sd = np.sqrt(np.diag(cov.values))
    corr = np.clip(cov.values / np.outer(sd, sd), -1.0, 1.0)
    dist = np.sqrt(np.clip((1 - corr) / 2, 0.0, None))
    np.fill_diagonal(dist, 0.0)
    order = list(leaves_list(linkage(squareform(dist, checks=False), method="single")))
    c = cov.values

    def cluster_var(idx: list[int]) -> float:
        sub = c[np.ix_(idx, idx)]
        ivp = 1.0 / np.diag(sub)
        ivp /= ivp.sum()
        return float(ivp @ sub @ ivp)

    w = np.ones(n)
    clusters = [order]
    while clusters:
        clusters = [
            half
            for cl in clusters
            if len(cl) > 1
            for half in (cl[: len(cl) // 2], cl[len(cl) // 2 :])
        ]
        for left, right in zip(clusters[::2], clusters[1::2]):
            vl, vr = cluster_var(left), cluster_var(right)
            alpha = 1 - vl / (vl + vr)
            w[left] *= alpha
            w[right] *= 1 - alpha
    return pd.Series(w / w.sum(), index=cov.index)


def _max_drawdown(w: pd.Series, window: pd.DataFrame) -> float:
    port = (window[w.index] * w).sum(axis=1)
    wealth = (1 + port).cumprod()
    return float((wealth / wealth.cummax() - 1).min())


def _vol(w: pd.Series, cov: pd.DataFrame) -> float:
    return float(np.sqrt(max(float(w @ cov @ w), 0.0)))


def _efficient(mu, cov, equity, eq_cap, target):
    """EfficientFrontier with optional equity cap; efficient_risk(target) or min_volatility()."""
    ef = EfficientFrontier(mu, cov, weight_bounds=(0, 1))
    if equity and eq_cap < 1:
        ef.add_sector_constraints(
            {t: "eq" if t in equity else "other" for t in mu.index}, {"eq": 0.0}, {"eq": eq_cap}
        )
    if target is None:
        ef.min_volatility()
    else:
        ef.efficient_risk(target)
    return pd.Series(ef.clean_weights(cutoff=0, rounding=None))


def _constrained(mu, cov, equity, eq_cap, cap, notes) -> pd.Series:
    try:
        return _efficient(mu, cov, equity, eq_cap, cap)
    except _SOLVER_ERRORS:
        pass
    try:
        w = _efficient(mu, cov, equity, eq_cap, None)
        notes.append(
            f"Volatility cap {cap:.2%} (sleeve) not achievable under the equity cap; "
            "fell back to the minimum-volatility portfolio."
        )
        return w
    except _SOLVER_ERRORS:
        w = _efficient(mu, cov, equity, 1.0, None)
        notes.append(
            f"Equity cap {eq_cap:.0%} cannot be met with this universe; "
            "fell back to the unconstrained minimum-volatility portfolio."
        )
        return w


def _hrp_adjust(w, cov, equity, eq_cap, cap, notes) -> pd.Series:
    """Enforce equity cap and vol cap on HRP weights.

    Equity excess is scaled down and given to the lowest-vol non-equity asset. If the sleeve
    vol is still above the cap, weight moves from the highest-vol assets to the lowest-vol asset
    (non-equity when an equity cap is active), bisecting the amount moved from each source.
    """
    w = w.copy()
    vols = pd.Series(np.sqrt(np.diag(cov)), index=cov.index)
    others = [t for t in w.index if t not in equity]
    if equity and eq_cap < 1:
        eq_w = float(w[list(equity)].sum())
        if eq_w > eq_cap:
            if not others:
                notes.append(
                    f"Equity cap {eq_cap:.0%} cannot be met with this universe; HRP weights kept."
                )
            else:
                w[list(equity)] *= eq_cap / eq_w
                w[vols[others].idxmin()] += eq_w - eq_cap
    dest_pool = others if (equity and eq_cap < 1 and others) else list(w.index)
    dest = vols[dest_pool].idxmin()
    for src in vols.sort_values(ascending=False).index:
        if _vol(w, cov) <= cap + 1e-9:
            break
        if src == dest or w[src] <= 0:
            continue
        full = w.copy()
        full[dest] += full[src]
        full[src] = 0.0
        if _vol(full, cov) > cap:
            w = full
            continue
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            trial = w.copy()
            trial[dest] += mid * w[src]
            trial[src] *= 1 - mid
            lo, hi = (lo, mid) if _vol(trial, cov) <= cap else (mid, hi)
        w[dest] += hi * w[src]
        w[src] *= 1 - hi
    if _vol(w, cov) > cap + 1e-9:
        notes.append(
            f"Volatility cap {cap:.2%} (sleeve) not achievable by HRP re-weighting; "
            "weights left at the lowest-volatility concentration reachable."
        )
    return w


def _bl_returns(tickers, cov, etfs_by_t, views) -> pd.Series:
    ref = load_reference_weights()
    classes = [etfs_by_t[t].asset_class for t in tickers]
    n_cls = pd.Series(classes).value_counts()
    present = {c: ref[c] for c in n_cls.index if c in ref}
    total = sum(present.values())
    if total <= 0:
        raise ValueError(
            "No reference weight for any asset class in the universe (Black-Litterman)."
        )
    w_ref = pd.Series([present.get(c, 0.0) / total / n_cls[c] for c in classes], index=tickers)
    pi = DELTA * cov.loc[tickers, tickers] @ w_ref
    if not views:
        return pi
    abs_views = {
        t: views[etfs_by_t[t].asset_class] for t in tickers if etfs_by_t[t].asset_class in views
    }
    if not abs_views:
        return pi
    bl = BlackLittermanModel(cov.loc[tickers, tickers], pi=pi, absolute_views=abs_views)
    return bl.bl_returns()


def optimise(
    method: Literal["markowitz", "black_litterman", "hrp"],
    tickers: list[str],
    mu: pd.Series,
    cov: pd.DataFrame,
    returns: pd.DataFrame,
    rule: ProfileRule,
    safe_share: float,
    max_equity_in_sleeve: float,
    views: dict[str, float] | None = None,
    etfs: list[ETF] | None = None,
) -> OptResult:
    if safe_share >= 1:
        return OptResult(
            weights=pd.Series(dtype=float),
            expected_return=0.0,
            volatility=0.0,
            max_drawdown=0.0,
            method=method,
            notes=["No risky sleeve: bucket fully in safe assets."],
        )
    tickers = list(tickers)
    etfs_by_t = {e.ticker: e for e in (etfs if etfs is not None else load_etfs())}
    equity = {t for t in tickers if etfs_by_t[t].asset_class.startswith("equity_")}
    cov = cov.loc[tickers, tickers]
    mu = mu.reindex(tickers)
    window = common_window(returns[tickers])
    cap = rule.vol_cap / (1 - safe_share)
    eq_cap = max_equity_in_sleeve
    notes: list[str] = []

    if method == "markowitz":
        w = _constrained(mu, cov, equity, eq_cap, cap, notes)
    elif method == "black_litterman":
        post = _bl_returns(tickers, cov, etfs_by_t, views)
        w = _constrained(post, cov, equity, eq_cap, cap, notes)
    elif method == "hrp":
        raw = _hrp_weights(cov)
        w = _hrp_adjust(raw, cov, equity, eq_cap, cap, notes)
    else:
        raise ValueError(f"Unknown method {method!r}")

    w = _clean(w.reindex(tickers).fillna(0.0))
    for tighten in (1e-5, 1e-4, 1e-3):
        over_vol = _vol(w, cov) > cap + 1e-9
        over_eq = bool(equity) and eq_cap < 1 and float(w[list(equity)].sum()) > eq_cap + 1e-9
        if notes or not (over_vol or over_eq):
            break
        # Zeroing tiny weights nudged a cap: re-trim just inside it, then re-clean.
        w = _clean(_hrp_adjust(w, cov, equity, eq_cap * (1 - tighten), cap * (1 - tighten), []))
    if _vol(w, cov) > cap + 1e-6 and not any("not achievable" in n for n in notes):
        notes.append(f"Volatility cap {cap:.2%} (sleeve) still exceeded after cleaning weights.")
    eq_left = float(w[list(equity)].sum()) if equity else 0.0
    if eq_cap < 1 and eq_left > eq_cap + 1e-6 and not any("Equity cap" in n for n in notes):
        notes.append(f"Equity cap {eq_cap:.0%} still exceeded after cleaning weights.")
    return OptResult(
        weights=w,
        expected_return=float(w @ mu),
        volatility=_vol(w, cov),
        max_drawdown=_max_drawdown(w, window),
        method=method,
        notes=notes,
    )

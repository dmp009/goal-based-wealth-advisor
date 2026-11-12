"""Shared risk/return model: Ledoit-Wolf covariance, CMA expected returns, portfolio statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from wealthadvisor.config import ETF

MIN_MONTHS = 36


def common_window(returns: pd.DataFrame) -> pd.DataFrame:
    """Rows where every ticker has data; raises ValueError under 36 months."""
    window = returns.dropna(how="any")
    if len(window) < MIN_MONTHS:
        raise ValueError(
            f"Common history window is {len(window)} months; at least {MIN_MONTHS} required."
        )
    return window


def covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """Ledoit-Wolf shrunk covariance of monthly returns over the common window, annualised x12."""
    window = common_window(returns)
    lw = LedoitWolf().fit(window.values)
    return pd.DataFrame(lw.covariance_ * 12, index=window.columns, columns=window.columns)


def expected_returns(tickers: list[str], etfs: list[ETF], cma: dict[str, float]) -> pd.Series:
    """Ticker -> capital-market-assumption return of its asset class."""
    cls = {e.ticker: e.asset_class for e in etfs}
    return pd.Series({t: cma[cls[t]] for t in tickers}, dtype=float)


def portfolio_stats(
    weights: pd.Series, mu: pd.Series, cov: pd.DataFrame, safe_share: float, safe_rate: float
) -> dict[str, float]:
    """BUCKET-level stats: risky sleeve scaled by (1 - safe_share), safe sleeve earns
    ``safe_rate`` with zero volatility. With safe_share = 0 these are the sleeve stats."""
    w = weights.astype(float)
    m = mu.reindex(w.index)
    c = cov.loc[w.index, w.index]
    sleeve_ret = float(w @ m)
    sleeve_vol = float(np.sqrt(max(float(w @ c @ w), 0.0)))
    return {
        "expected_return": (1 - safe_share) * sleeve_ret + safe_share * safe_rate,
        "volatility": (1 - safe_share) * sleeve_vol,
    }

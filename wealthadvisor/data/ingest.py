"""Monthly price ingestion from yfinance and proxy back-fill for short-history ETFs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from wealthadvisor.config import REPO_ROOT

RAW_DIR = REPO_ROOT / "data" / "raw" / "yfinance"


def fetch_monthly(ticker: str, raw_dir: Path = RAW_DIR) -> pd.Series:
    """Month-end adjusted close. Saves the raw yfinance response before resampling.

    The current (incomplete) month is dropped so a partial month never enters the history.
    """
    import yfinance as yf

    raw = yf.Ticker(ticker).history(period="max", auto_adjust=True)
    if raw.empty:
        raise ValueError(f"No price data returned for {ticker}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    raw.to_csv(raw_dir / f"{stamp}_{ticker.replace('^', '')}.csv")
    close = raw["Close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    monthly = close.resample("ME").last().dropna()
    current_month_end = (
        pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    ) + pd.offsets.MonthEnd(0)
    monthly = monthly[monthly.index < current_month_end]
    monthly.name = ticker
    return monthly


def backfill_with_proxy(etf: pd.Series, proxy: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Extend ``etf`` backwards using the proxy's returns, anchored on the ETF's first price.

    Returns (series, is_proxy flags). Dates before the ETF's first date that the proxy covers are
    proxy-derived; the ETF's own prices are never modified.
    """
    etf = etf.dropna().sort_index()
    proxy = proxy.dropna().sort_index()
    own_flags = pd.Series(False, index=etf.index)
    if etf.empty:
        return etf, own_flags
    first = etf.index[0]
    earlier = proxy[proxy.index < first]
    anchor = proxy[proxy.index <= first]
    if earlier.empty or anchor.empty:
        return etf, own_flags
    scaled = earlier * (etf.iloc[0] / anchor.iloc[-1])
    series = pd.concat([scaled, etf]).sort_index()
    flags = pd.Series([False] * len(series), index=series.index)
    flags.loc[scaled.index] = True
    series.name = etf.name
    return series, flags.astype(bool)

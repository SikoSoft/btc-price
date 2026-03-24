"""
Metric helper functions for bitcoin_analyzer.

All functions are pure (no side effects) and operate on a pandas DataFrame
with a DatetimeIndex and at minimum a 'close' column.  High/low/volume are
used where available and fall back gracefully when absent.
"""

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def to_dataframe(rows: list[dict]) -> pd.DataFrame:
    """
    Convert a list of price dicts (as returned by db.get_price_range) to a
    DataFrame indexed by date (DatetimeIndex, ascending).

    Columns: open, high, low, close, volume  (NaN where not available).
    """
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan
    return df[numeric_cols]


# ---------------------------------------------------------------------------
# Return / momentum metrics
# ---------------------------------------------------------------------------

def daily_returns(df: pd.DataFrame) -> pd.Series:
    """
    Day-over-day percentage change in close price.
    Returns NaN for the first row.
    """
    return df["close"].pct_change()


def rolling_momentum(df: pd.DataFrame, window: int) -> pd.Series:
    """
    N-day rate of change: (close[t] - close[t-N]) / close[t-N].

    Positive → upward trend over the window.
    Negative → downward trend.
    NaN for the first N rows.
    """
    return df["close"].pct_change(periods=window)


# ---------------------------------------------------------------------------
# Volatility metrics
# ---------------------------------------------------------------------------

def rolling_volatility(df: pd.DataFrame, window: int) -> pd.Series:
    """
    Rolling standard deviation of daily returns over `window` days.

    Higher value → more price variability.
    NaN for the first `window` rows.
    """
    returns = daily_returns(df)
    return returns.rolling(window=window).std()


def rolling_atr(df: pd.DataFrame, window: int) -> pd.Series:
    """
    Average True Range (ATR) over `window` days.

    True Range at t = max(
        high[t] - low[t],
        |high[t] - close[t-1]|,
        |low[t]  - close[t-1]|,
    )

    Falls back to |close[t] - close[t-1]| when high/low are unavailable.
    """
    if df["high"].isna().all() or df["low"].isna().all():
        # Graceful fallback for providers that only return close prices.
        tr = df["close"].diff().abs()
    else:
        prev_close = df["close"].shift(1)
        hl  = df["high"] - df["low"]
        hpc = (df["high"] - prev_close).abs()
        lpc = (df["low"]  - prev_close).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)

    return tr.rolling(window=window).mean()

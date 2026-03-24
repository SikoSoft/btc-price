"""
Anomaly detection functions for bitcoin_analyzer.

Each detector is a pure function:

    detect_*(df: pd.DataFrame, config: dict) -> pd.DataFrame

The returned DataFrame has a DatetimeIndex and the following columns:
    score     float   — higher means stronger anomaly
    type      str     — 'reversal' | 'amplification' | 'stagnation'
    metadata  str     — JSON blob with supporting numeric detail

Config keys consumed by each detector are documented below; all have
sensible defaults so callers can pass an empty dict for exploration.
"""

import json

import numpy as np
import pandas as pd

from analysis.metrics import rolling_momentum, rolling_volatility


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _records_to_df(records: list[dict]) -> pd.DataFrame:
    """Convert a list of record dicts to a DataFrame with a DatetimeIndex."""
    if not records:
        return pd.DataFrame(columns=["score", "type", "metadata"])
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _suppress_overlapping(
    records: list[dict],
    min_gap_days: int,
) -> list[dict]:
    """
    Greedy non-maximum suppression.

    Given records already sorted by score descending, discard any record
    whose date falls within `min_gap_days` of an already-selected record.
    This ensures the returned set represents genuinely distinct periods.
    """
    selected: list[dict] = []
    selected_ts: list[pd.Timestamp] = []

    for rec in records:
        ts = pd.Timestamp(rec["date"])
        too_close = any(
            abs((ts - sel).days) < min_gap_days for sel in selected_ts
        )
        if not too_close:
            selected.append(rec)
            selected_ts.append(ts)

    return selected


# ---------------------------------------------------------------------------
# Reversals
# ---------------------------------------------------------------------------

def detect_reversals(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Identify days where price direction reverses most sharply.

    Algorithm
    ---------
    1. Compute backward momentum  B[t] = pct_change over `lookback` days
       ending at t.
    2. Compute forward  momentum  F[t] = pct_change over `lookforward` days
       starting at t  (= pct_change(lookforward).shift(-lookforward)).
    3. Keep only days where sign(B) != sign(F)  (direction flip).
    4. Score = |F - B|   — larger gap between the two momenta = stronger
       reversal.

    Config keys
    -----------
    reversal_lookback   int    Days of backward momentum window  (default 10)
    reversal_lookforward int   Days of forward  momentum window  (default 10)
    reversal_min_score  float  Minimum score to include          (default 0.05)
    """
    lookback   = int(config.get("reversal_lookback",    10))
    lookforward = int(config.get("reversal_lookforward", 10))
    min_score  = float(config.get("reversal_min_score", 0.05))

    backward = rolling_momentum(df, lookback)
    # shift(-lookforward) maps the N-day-forward pct_change onto the start date
    forward  = rolling_momentum(df, lookforward).shift(-lookforward)

    both_valid = backward.notna() & forward.notna()
    sign_flip  = np.sign(backward) != np.sign(forward)

    raw_score = (forward - backward).abs()
    score     = raw_score.where(both_valid & sign_flip).dropna()
    score     = score[score >= min_score]

    records = [
        {
            "date":  date,
            "score": float(s),
            "type":  "reversal",
            "metadata": json.dumps({
                "backward_momentum": round(float(backward[date]), 4),
                "forward_momentum":  round(float(forward[date]),  4),
                "close":             round(float(df.loc[date, "close"]), 2),
            }),
        }
        for date, s in score.items()
    ]

    return _records_to_df(records)


# ---------------------------------------------------------------------------
# Amplifications
# ---------------------------------------------------------------------------

def detect_amplifications(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Identify days where price movement suddenly accelerates in the same
    direction (the "second derivative" of price).

    Algorithm
    ---------
    Same backward / forward momentum calculation as reversals, but here we
    require sign(B) == sign(F)  — same direction — AND |F| > |B| —
    acceleration.

    Score = |F - B|   — larger gap = stronger acceleration.

    Config keys
    -----------
    amplification_lookback   int    (default 10)
    amplification_lookforward int   (default 10)
    amplification_min_score  float  (default 0.05)
    """
    lookback    = int(config.get("amplification_lookback",    10))
    lookforward  = int(config.get("amplification_lookforward", 10))
    min_score   = float(config.get("amplification_min_score", 0.05))

    backward = rolling_momentum(df, lookback)
    forward  = rolling_momentum(df, lookforward).shift(-lookforward)

    both_valid   = backward.notna() & forward.notna()
    same_sign    = np.sign(backward) == np.sign(forward)
    accelerating = forward.abs() > backward.abs()

    raw_score = (forward - backward).abs()
    score     = raw_score.where(both_valid & same_sign & accelerating).dropna()
    score     = score[score >= min_score]

    records = [
        {
            "date":  date,
            "score": float(s),
            "type":  "amplification",
            "metadata": json.dumps({
                "backward_momentum": round(float(backward[date]), 4),
                "forward_momentum":  round(float(forward[date]),  4),
                "direction":         "up" if float(forward[date]) > 0 else "down",
                "close":             round(float(df.loc[date, "close"]), 2),
            }),
        }
        for date, s in score.items()
    ]

    return _records_to_df(records)


# ---------------------------------------------------------------------------
# Stagnations
# ---------------------------------------------------------------------------

def detect_stagnations(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Identify the quietest, flattest periods in the price history.

    Algorithm
    ---------
    1. Compute rolling volatility (std of daily returns) over `window` days.
    2. Invert it so that low volatility = high score.
    3. Normalise scores to [0, 1] across the full history.
    4. Apply greedy non-overlapping suppression so the top results represent
       distinct quiet periods (not adjacent days inside the same quiet stretch).

    The date attached to each record is the *end* of its rolling window.
    The window_start / window_end fields in metadata give the full span.

    Config keys
    -----------
    stagnation_window    int    Rolling window in days       (default 30)
    stagnation_min_score float  Minimum normalised score     (default 0.0)
    """
    window    = int(config.get("stagnation_window",    30))
    min_score = float(config.get("stagnation_min_score", 0.0))

    vol   = rolling_volatility(df, window).dropna()
    if vol.empty:
        return pd.DataFrame(columns=["score", "type", "metadata"])

    # Invert: low volatility → high score.  Add epsilon to avoid div-by-zero.
    inv   = 1.0 / (vol + 1e-10)

    # Normalise to [0, 1] so scores are comparable with other categories.
    vmin, vmax = inv.min(), inv.max()
    norm  = (inv - vmin) / (vmax - vmin + 1e-10)
    norm  = norm[norm >= min_score]

    # Build records sorted by score desc before suppression.
    records = [
        {
            "date":  date,
            "score": float(s),
            "type":  "stagnation",
            "metadata": json.dumps({
                "window_start": str((date - pd.Timedelta(days=window - 1)).date()),
                "window_end":   str(date.date()),
                "volatility":   round(float(vol[date]), 6),
                "close":        round(float(df.loc[date, "close"]), 2),
            }),
        }
        for date, s in norm.items()
    ]
    records.sort(key=lambda r: r["score"], reverse=True)

    # Suppress overlapping windows so every selected period is distinct.
    records = _suppress_overlapping(records, min_gap_days=window)

    return _records_to_df(records)

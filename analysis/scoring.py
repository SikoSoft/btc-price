"""
Scoring and selection utilities for bitcoin_analyzer.

Primary entry point:

    results = run_all(df, config)

Returns a dict with the top-N anomalies per category plus a config hash
that can be used to key results in the SQLite cache.
"""

import hashlib
import json

import pandas as pd

from analysis.anomalies import (
    detect_amplifications,
    detect_reversals,
    detect_stagnations,
)


# ---------------------------------------------------------------------------
# Config hashing
# ---------------------------------------------------------------------------

def hash_config(config: dict) -> str:
    """
    Return a stable SHA-256 hex digest of a config dict.

    The dict is serialised with sorted keys and no extra whitespace so the
    hash is identical regardless of insertion order.  Used to key cached
    anomaly results in the database.
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def top_n(scored_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Return the top `n` rows from a scored DataFrame, sorted by score desc."""
    if scored_df.empty:
        return scored_df
    return scored_df.nlargest(n, "score")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_all(df: pd.DataFrame, config: dict) -> dict:
    """
    Run all three anomaly detectors and return the top-N per category.

    Parameters
    ----------
    df      : DataFrame produced by analysis.metrics.to_dataframe()
    config  : Dict of detection parameters (see anomalies.py for keys).
              Pass an empty dict to use all defaults.

    Returns
    -------
    {
        "reversals":      [ {id, type, date, score, config_hash, metadata}, ... ],
        "amplifications": [ ... ],
        "stagnations":    [ ... ],
        "config_hash":    str,
    }

    Each list is sorted by score descending and contains at most `top_n`
    entries (default 10, overridable via config["top_n"]).
    """
    n           = int(config.get("top_n", 10))
    cfg_hash    = hash_config(config)

    reversals_df      = top_n(detect_reversals(df,      config), n)
    amplifications_df = top_n(detect_amplifications(df, config), n)
    stagnations_df    = top_n(detect_stagnations(df,    config), n)

    def _to_records(category_df: pd.DataFrame) -> list[dict]:
        if category_df.empty:
            return []
        out = []
        for date, row in category_df.iterrows():
            out.append({
                "id":          f"{row['type']}_{date.date()}",
                "type":        row["type"],
                "date":        str(date.date()),
                "score":       round(float(row["score"]), 6),
                "config_hash": cfg_hash,
                "metadata":    row.get("metadata", "{}"),
            })
        # Guarantee descending score order after the DatetimeIndex iteration.
        out.sort(key=lambda r: r["score"], reverse=True)
        return out

    return {
        "reversals":      _to_records(reversals_df),
        "amplifications": _to_records(amplifications_df),
        "stagnations":    _to_records(stagnations_df),
        "config_hash":    cfg_hash,
    }

"""
POST /anomalies

Runs anomaly detection against the full price history and returns the
top-N results per category (reversals, amplifications, stagnations).

Config-hash caching
-------------------
Detection is expensive (~1 second on the full dataset).  The results are
keyed by a SHA-256 hash of the submitted config dict so that identical
configs are served from the SQLite cache rather than recomputed.

The frontend should POST the full config dict any time a slider changes.
If the hash matches a cached run, the response is immediate.  Otherwise,
detection runs, results are stored, and the (potentially slow) response
is returned.  The frontend uses the loading state during this window.
"""

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import DbConn
from config import default_analysis_config
from db.database import get_anomalies, get_cache_status, get_price_range, upsert_anomalies
from analysis.metrics import to_dataframe
from analysis.scoring import hash_config, run_all

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalysisConfig(BaseModel):
    """
    Anomaly detection parameters.  All fields are optional — omitted fields
    fall back to the current server-side defaults.
    """
    reversal_lookback:        int   | None = Field(default=None, ge=1, le=365)
    reversal_lookforward:     int   | None = Field(default=None, ge=1, le=365)
    reversal_min_score:       float | None = Field(default=None, ge=0.0, le=10.0)

    amplification_lookback:   int   | None = Field(default=None, ge=1, le=365)
    amplification_lookforward: int  | None = Field(default=None, ge=1, le=365)
    amplification_min_score:  float | None = Field(default=None, ge=0.0, le=10.0)

    stagnation_window:        int   | None = Field(default=None, ge=5, le=365)
    stagnation_min_score:     float | None = Field(default=None, ge=0.0, le=1.0)

    top_n:                    int   | None = Field(default=None, ge=1, le=50)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_config(body: AnalysisConfig) -> dict:
    """Merge submitted fields over server defaults."""
    cfg = default_analysis_config()
    overrides = body.model_dump(exclude_none=True)
    cfg.update(overrides)
    return cfg


def _run_and_cache(conn: sqlite3.Connection, cfg: dict) -> dict:
    """Run detection, persist results, return the run_all() output dict."""
    status = get_cache_status(conn)
    if status["total_rows"] == 0:
        raise HTTPException(
            status_code=503,
            detail="No price data. Run scripts/fetch_prices.py first.",
        )

    rows = get_price_range(conn, status["earliest_date"], status["latest_date"])
    df   = to_dataframe(rows)
    results = run_all(df, cfg)

    all_anomalies = (
        results["reversals"]
        + results["amplifications"]
        + results["stagnations"]
    )
    upsert_anomalies(conn, all_anomalies)

    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("")
def detect_anomalies(body: AnalysisConfig, conn: DbConn):
    """
    Run anomaly detection with the provided config and return results.

    If the same config was used before, cached results are returned
    immediately.  Otherwise, detection runs (typically < 2 seconds) and
    the new results are cached before responding.

    Response shape:
        {
          "config_hash": str,
          "cached":      bool,
          "config":      {...},
          "reversals":      [ anomaly, ... ],
          "amplifications": [ anomaly, ... ],
          "stagnations":    [ anomaly, ... ],
        }
    """
    cfg      = _build_config(body)
    cfg_hash = hash_config(cfg)

    # Check cache first.  Only trust it when all three categories are present
    # (a partial cache can exist if a previous run was interrupted mid-way).
    expected_n = cfg.get("top_n", 10)
    cached = get_anomalies(conn, cfg_hash)
    types_present = {a["type"] for a in cached}
    cache_complete = types_present >= {"reversal", "amplification", "stagnation"}

    if cache_complete:
        by_type: dict[str, list] = {
            "reversals": [], "amplifications": [], "stagnations": []
        }
        for a in cached:
            by_type[a["type"] + "s"].append(dict(a))

        return {
            "config_hash":    cfg_hash,
            "cached":         True,
            "config":         cfg,
            **by_type,
        }

    # Cache miss (or incomplete) — run detection.
    results  = _run_and_cache(conn, cfg)
    return {
        "config_hash":    cfg_hash,
        "cached":         False,
        "config":         cfg,
        "reversals":      results["reversals"],
        "amplifications": results["amplifications"],
        "stagnations":    results["stagnations"],
    }


@router.get("/cached")
def list_cached_runs(conn: DbConn):
    """
    List all config hashes that have cached anomaly results in the DB.
    Useful for the frontend to know whether the default config is already
    cached on first load (avoiding a full analysis round-trip).
    """
    rows = conn.execute(
        """
        SELECT config_hash, COUNT(*) as count, MIN(date) as earliest, MAX(date) as latest
        FROM   anomalies
        GROUP  BY config_hash
        ORDER  BY count DESC
        """
    ).fetchall()

    return {
        "cached_runs": [dict(r) for r in rows]
    }

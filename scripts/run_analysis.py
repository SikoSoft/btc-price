#!/usr/bin/env python3
"""
Run the full anomaly-detection pipeline against the local SQLite database
and print a summary of the top anomalies found.

Usage
-----
    python scripts/run_analysis.py                   # default config
    python scripts/run_analysis.py --lookback 14     # override one param
    python scripts/run_analysis.py --json            # machine-readable output

Options
-------
  --lookback   INT    Momentum lookback window in days  (default from config)
  --lookforward INT   Momentum lookforward window       (default from config)
  --stag-window INT   Stagnation rolling window         (default from config)
  --top-n      INT    Anomalies to return per category  (default 10)
  --json              Print full results as JSON instead of a summary table
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Make sure the project root is on sys.path so imports work whether this
# script is run from the project root or from the scripts/ subdirectory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import DB_PATH, default_analysis_config
from db.database import get_price_range, get_cache_status, init_db
from analysis.metrics import to_dataframe
from analysis.scoring import run_all


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Detect Bitcoin price anomalies from local OHLCV data."
    )
    p.add_argument("--lookback",     type=int,   help="Momentum lookback days")
    p.add_argument("--lookforward",  type=int,   help="Momentum lookforward days")
    p.add_argument("--stag-window",  type=int,   dest="stag_window",
                   help="Stagnation rolling window days")
    p.add_argument("--top-n",        type=int,   dest="top_n",
                   help="Anomalies per category (default 10)")
    p.add_argument("--json",         action="store_true",
                   help="Print full results as JSON")
    return p


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _bar(score: float, width: int = 30) -> str:
    """Simple ASCII progress bar scaled to [0, 1] scores."""
    filled = int(round(score * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _print_category(label: str, anomalies: list[dict]) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {label}  ({len(anomalies)} results)")
    print(f"{'─' * 60}")
    if not anomalies:
        print("  (no results)")
        return
    for i, a in enumerate(anomalies, 1):
        meta = json.loads(a["metadata"])
        score_bar = _bar(min(a["score"], 1.0))
        print(f"  {i:>2}. {a['date']}   score={a['score']:.4f}  {score_bar}")
        # Print a few key metadata fields
        detail_parts = []
        for key in ("backward_momentum", "forward_momentum",
                    "direction", "volatility",
                    "window_start", "window_end"):
            if key in meta:
                val = meta[key]
                if isinstance(val, float):
                    detail_parts.append(f"{key}={val:.4f}")
                else:
                    detail_parts.append(f"{key}={val}")
        if "close" in meta:
            detail_parts.append(f"close=${meta['close']:,.0f}")
        if detail_parts:
            print(f"       {', '.join(detail_parts)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = build_parser().parse_args()

    # Build config from defaults, then apply any CLI overrides.
    cfg = default_analysis_config()
    if args.lookback:
        cfg["reversal_lookback"]       = args.lookback
        cfg["amplification_lookback"]  = args.lookback
    if args.lookforward:
        cfg["reversal_lookforward"]       = args.lookforward
        cfg["amplification_lookforward"]  = args.lookforward
    if args.stag_window:
        cfg["stagnation_window"] = args.stag_window
    if args.top_n:
        cfg["top_n"] = args.top_n

    # Connect to DB and verify data is present.
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    status = get_cache_status(conn)

    if status["total_rows"] == 0:
        print("ERROR: No price data found. Run scripts/fetch_prices.py first.")
        sys.exit(1)

    print(f"Loaded {status['total_rows']} price rows  "
          f"({status['earliest_date']} → {status['latest_date']})")

    # Pull all available rows as a DataFrame.
    rows = get_price_range(conn, status["earliest_date"], status["latest_date"])
    conn.close()

    df = to_dataframe(rows)

    # Run detection.
    print(f"\nRunning analysis with config:")
    for k, v in cfg.items():
        print(f"  {k}: {v}")

    results = run_all(df, cfg)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    # Human-readable summary.
    total = (
        len(results["reversals"])
        + len(results["amplifications"])
        + len(results["stagnations"])
    )
    print(f"\nFound {total} anomalies total   config_hash={results['config_hash'][:12]}…")

    _print_category("REVERSALS      (sudden direction flip)", results["reversals"])
    _print_category("AMPLIFICATIONS (sudden acceleration)",   results["amplifications"])
    _print_category("STAGNATIONS    (quietest periods)",      results["stagnations"])

    print(f"\n{'─' * 60}\n")


if __name__ == "__main__":
    main()

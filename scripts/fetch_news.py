#!/usr/bin/env python3
"""
Fetch and cache news articles for all detected price anomalies.

This script:
  1. Loads price data from the local SQLite database.
  2. Runs anomaly detection (or loads cached anomalies for the same config).
  3. For each anomaly, queries GDELT for the top N news articles in the
     window_days before the anomaly date.
  4. Stores all results in the database for use by the API layer.

Usage
-----
    python scripts/fetch_news.py                    # use default config
    python scripts/fetch_news.py --force-refresh    # re-fetch all news
    python scripts/fetch_news.py --lookback 14      # custom analysis config
    python scripts/fetch_news.py --window 5         # 5-day news window
    python scripts/fetch_news.py --anomaly reversal_2017-12-17  # single anomaly
    python scripts/fetch_news.py --json             # JSON output

Options
-------
  --force-refresh      Re-fetch news even if already cached
  --window   INT       Days before anomaly to search (default 3)
  --top-n    INT       Max articles per anomaly (default 10)
  --lookback INT       Anomaly detection lookback days
  --lookforward INT    Anomaly detection lookforward days
  --stag-window INT    Stagnation window days
  --anomaly  ID        Fetch news for one specific anomaly ID only
  --json               Print results as JSON
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    DB_PATH,
    GDELT_MAX_RETRIES,
    GDELT_SLEEP_SECONDS,
    GDELT_TIMEOUT,
    NEWS_TOP_N,
    NEWS_WINDOW_DAYS,
    default_analysis_config,
)
from db.database import (
    get_cache_status,
    get_news_for_anomaly,
    get_price_range,
    init_db,
)
from analysis.metrics import to_dataframe
from analysis.scoring import run_all, hash_config
from news.aggregator import NewsAggregator
from news.providers.gdelt import GDELTProvider
from news.sources import NEWS_SOURCES


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fetch and cache news for Bitcoin price anomalies."
    )
    p.add_argument("--force-refresh", action="store_true",
                   help="Re-fetch news even if already cached")
    p.add_argument("--window",      type=int, help="News search window (days)")
    p.add_argument("--top-n",       type=int, dest="top_n",
                   help="Max articles per anomaly")
    p.add_argument("--lookback",    type=int,
                   help="Anomaly detection lookback days")
    p.add_argument("--lookforward", type=int,
                   help="Anomaly detection lookforward days")
    p.add_argument("--stag-window", type=int, dest="stag_window",
                   help="Stagnation detection window days")
    p.add_argument("--anomaly",     type=str,
                   help="Fetch news for a single anomaly ID only")
    p.add_argument("--json",        action="store_true",
                   help="Print full results as JSON")
    return p


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------

def make_progress(total: int, quiet: bool):
    """Return a progress callback suitable for NewsAggregator.run()."""
    def callback(current: int, _total: int, anomaly_id: str) -> None:
        if not quiet:
            bar_w  = 30
            filled = int(bar_w * current / _total)
            bar    = "#" * filled + "-" * (bar_w - filled)
            print(
                f"\r  [{bar}] {current}/{_total}  {anomaly_id:<40}",
                end="",
                flush=True,
            )
            if current == _total:
                print()  # newline on completion
    return callback


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = build_parser().parse_args()

    # Build analysis config.
    cfg = default_analysis_config()
    if args.lookback:
        cfg["reversal_lookback"]       = args.lookback
        cfg["amplification_lookback"]  = args.lookback
    if args.lookforward:
        cfg["reversal_lookforward"]       = args.lookforward
        cfg["amplification_lookforward"]  = args.lookforward
    if args.stag_window:
        cfg["stagnation_window"] = args.stag_window

    window  = args.window  or NEWS_WINDOW_DAYS
    top_n   = args.top_n   or NEWS_TOP_N

    # Open DB.
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    status = get_cache_status(conn)

    if status["total_rows"] == 0:
        print("ERROR: No price data. Run scripts/fetch_prices.py first.")
        sys.exit(1)

    if not args.json:
        print(f"Price data: {status['total_rows']} rows  "
              f"({status['earliest_date']} → {status['latest_date']})")

    # Detect anomalies.
    rows = get_price_range(conn, status["earliest_date"], status["latest_date"])
    df   = to_dataframe(rows)
    detection_results = run_all(df, cfg)
    cfg_hash = detection_results["config_hash"]

    flat_anomalies = (
        detection_results["reversals"]
        + detection_results["amplifications"]
        + detection_results["stagnations"]
    )

    # If a single anomaly was requested, filter to just that one.
    if args.anomaly:
        flat_anomalies = [a for a in flat_anomalies if a["id"] == args.anomaly]
        if not flat_anomalies:
            print(f"ERROR: Anomaly '{args.anomaly}' not found in current config.")
            sys.exit(1)

    if not args.json:
        print(f"Anomalies: {len(flat_anomalies)} total  "
              f"(config_hash={cfg_hash[:12]}…)")
        print(f"News window: {window} days before each anomaly  "
              f"| top {top_n} articles each")
        print(f"Provider: GDELT DOC 2.0  "
              f"| Sources: {len(NEWS_SOURCES)}")
        print()
        print("Fetching news…")

    # Build aggregator and run.
    provider   = GDELTProvider(
        sleep_seconds=GDELT_SLEEP_SECONDS,
        max_retries=GDELT_MAX_RETRIES,
        timeout=GDELT_TIMEOUT,
    )
    aggregator = NewsAggregator(
        conn,
        provider,
        NEWS_SOURCES,
        window_days=window,
        top_n=top_n,
        sleep_between=GDELT_SLEEP_SECONDS,
    )

    results = aggregator.run(
        flat_anomalies,
        force_refresh=args.force_refresh,
        progress_callback=make_progress(len(flat_anomalies), args.json),
    )

    conn.close()

    # Output.
    if args.json:
        print(json.dumps(results, indent=2))
        return

    # Human-readable summary.
    print()
    total_articles = sum(len(r["articles"]) for r in results)
    fetched        = sum(1 for r in results if r["articles"])
    print(f"Done.  {total_articles} articles cached across "
          f"{fetched}/{len(results)} anomalies.")
    print()

    # Group by type for display.
    by_type: dict[str, list] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r)

    for atype, anomalies in by_type.items():
        print(f"  {atype.upper()}")
        for a in anomalies:
            n = len(a["articles"])
            status_icon = "✓" if n > 0 else "○"
            print(f"    {status_icon} {a['date']}  score={a['score']:.4f}  "
                  f"{n} article{'s' if n != 1 else ''}")
            for art in a["articles"][:3]:
                print(f"        [{art['source_name']}] {art['title'][:70]}")
            if n > 3:
                print(f"        … and {n - 3} more")
        print()


if __name__ == "__main__":
    main()

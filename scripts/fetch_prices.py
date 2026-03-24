"""
CLI utility for managing the Bitcoin price cache.

Usage examples
--------------
# Initial full-history load (CoinGecko, recommended for first run):
  python scripts/fetch_prices.py

# Show what's currently in the database without fetching anything:
  python scripts/fetch_prices.py --status

# Use Kraken for the most recent 90 days of proper OHLCV data:
  python scripts/fetch_prices.py --provider kraken --start-date 2023-01-01

# Force a complete re-fetch of a specific window:
  python scripts/fetch_prices.py --start-date 2024-01-01 --end-date 2024-12-31 --force-refresh

# Use a non-default database path:
  python scripts/fetch_prices.py --db-path /tmp/test.db
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# Allow running as `python scripts/fetch_prices.py` from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from data.cache import HISTORY_START, get_status, sync_prices
from data.providers import get_provider
from db.database import init_db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fetch_prices")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and cache Bitcoin daily price data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--provider",
        choices=["bitfinex", "coingecko", "kraken"],
        default=config.DEFAULT_PROVIDER,
        help=(
            "Data provider to use. "
            "'bitfinex' (default): no key required, full OHLCV, history back to 2013. "
            "'coingecko': requires a free API key (COINGECKO_API_KEY env var), "
            "close + volume only, full history. "
            "'kraken': no key required, full OHLCV, most recent ~720 days only. "
            f"Default: {config.DEFAULT_PROVIDER}"
        ),
    )

    parser.add_argument(
        "--start-date",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "Earliest date to fetch.  "
            f"Defaults to {HISTORY_START.isoformat()} for CoinGecko, "
            "or 720 days ago for Kraken."
        ),
    )

    parser.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "Latest date to fetch (inclusive).  "
            "Defaults to yesterday (today's candle may not be finalised)."
        ),
    )

    parser.add_argument(
        "--db-path",
        default=config.DB_PATH,
        help=f"Path to the SQLite database file. Default: {config.DB_PATH}",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Print a cache status summary and exit without fetching.",
    )

    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help=(
            "Re-fetch and upsert data even if it already exists in the "
            "database.  Useful for correcting data quality issues."
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output results as JSON (useful for scripting).",
    )

    return parser


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_status(status: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(status, indent=2))
        return

    print("\n─── Price Cache Status ────────────────────────────────")
    print(f"  Database rows    : {status['total_rows']:,}")
    print(f"  Earliest date    : {status['earliest_date'] or 'n/a'}")
    print(f"  Latest date      : {status['latest_date'] or 'n/a'}")
    print(f"  Coverage         : {status['coverage_pct']}% of days since "
          f"{status['history_start']}")
    print(f"  Gap count        : {status['gap_count']}")
    if status["gaps"]:
        shown = status["gaps"][:5]
        more = status["gap_count"] - len(shown)
        gap_str = ", ".join(shown)
        if more > 0:
            gap_str += f" … (+{more} more)"
        print(f"  First gaps       : {gap_str}")
    print(f"  Rows by source   : {status['rows_by_source']}")
    print("────────────────────────────────────────────────────────\n")


def print_sync_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
        return

    print("\n─── Sync Result ───────────────────────────────────────")
    if result["skipped"]:
        print("  ✓ Database already up to date — nothing fetched.")
    else:
        print(f"  Provider         : {result['provider']}")
        print(f"  Rows fetched     : {result['rows_fetched']:,}")
        print(f"  Rows written     : {result['rows_written']:,}")
        print(f"  Date range       : {result['start_date']} → {result['end_date']}")
    print("────────────────────────────────────────────────────────\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve and validate date arguments.
    start_date: date | None = None
    end_date: date | None = None

    if args.start_date:
        try:
            start_date = date.fromisoformat(args.start_date)
        except ValueError:
            parser.error(f"Invalid --start-date: '{args.start_date}'. Use YYYY-MM-DD.")

    if args.end_date:
        try:
            end_date = date.fromisoformat(args.end_date)
        except ValueError:
            parser.error(f"Invalid --end-date: '{args.end_date}'. Use YYYY-MM-DD.")

    if start_date and end_date and start_date > end_date:
        parser.error("--start-date must be before --end-date.")

    # Open the database.
    db_path = args.db_path
    logger.info("Using database: %s", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance.
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        init_db(conn)

        # --status: just show current state and exit.
        if args.status:
            status = get_status(conn)
            print_status(status, args.output_json)
            return 0

        # Fetch / sync.
        provider = get_provider(args.provider)
        logger.info("Provider: %s", provider.name)

        result = sync_prices(
            conn,
            provider,
            start=start_date,
            end=end_date,
            force_refresh=args.force_refresh,
        )

        print_sync_result(result, args.output_json)

        # Print updated status after a successful fetch.
        if not result["skipped"] and not args.output_json:
            status = get_status(conn)
            print_status(status, as_json=False)

        return 0

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        return 130

    except Exception as exc:  # noqa: BLE001
        logger.error("Fatal error: %s", exc, exc_info=True)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

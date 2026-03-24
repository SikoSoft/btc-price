"""
SQLite database layer for bitcoin_analyzer.

Responsibilities:
  - Schema creation / migration
  - Upsert of price rows
  - Read queries used by the analysis and cache layers
  - Gap detection (identifying missing dates in a range)

All functions accept an open sqlite3.Connection as their first argument so
callers control the connection lifecycle.  This keeps the module stateless
and easy to test with an in-memory database.

Schema (prices table):
    date        TEXT PRIMARY KEY   YYYY-MM-DD, UTC
    open        REAL               NULL when unavailable (e.g. CoinGecko)
    high        REAL               NULL when unavailable
    low         REAL               NULL when unavailable
    close       REAL NOT NULL
    volume      REAL               NULL when unavailable
    source      TEXT NOT NULL      'coingecko' | 'kraken' | 'csv'
    fetched_at  TEXT NOT NULL      ISO-8601 datetime of insertion (UTC)
"""

import sqlite3
from datetime import date, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS prices (
    date       TEXT PRIMARY KEY,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL NOT NULL,
    volume     REAL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    provider      TEXT    NOT NULL,
    fetched_at    TEXT    NOT NULL,
    start_date    TEXT    NOT NULL,
    end_date      TEXT    NOT NULL,
    rows_affected INTEGER NOT NULL
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they do not already exist."""
    conn.executescript(_DDL)
    conn.commit()


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def upsert_prices(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    """
    Insert or replace a list of price rows.

    Args:
        conn: Open SQLite connection.
        rows: Each dict must contain at minimum the keys:
              date, close, source, fetched_at.
              open, high, low, volume default to None if absent.

    Returns:
        Number of rows inserted or replaced.
    """
    if not rows:
        return 0

    sql = """
        INSERT OR REPLACE INTO prices
            (date, open, high, low, close, volume, source, fetched_at)
        VALUES
            (:date, :open, :high, :low, :close, :volume, :source, :fetched_at)
    """

    # Normalise rows: fill in missing optional keys with None.
    normalised = [
        {
            "date":       r["date"],
            "open":       r.get("open"),
            "high":       r.get("high"),
            "low":        r.get("low"),
            "close":      r["close"],
            "volume":     r.get("volume"),
            "source":     r["source"],
            "fetched_at": r["fetched_at"],
        }
        for r in rows
    ]

    conn.executemany(sql, normalised)
    conn.commit()
    return len(normalised)


def log_fetch(
    conn: sqlite3.Connection,
    provider: str,
    fetched_at: str,
    start_date: str,
    end_date: str,
    rows_affected: int,
) -> None:
    """Append a record to the fetch audit log."""
    conn.execute(
        """
        INSERT INTO fetch_log (provider, fetched_at, start_date, end_date, rows_affected)
        VALUES (?, ?, ?, ?, ?)
        """,
        (provider, fetched_at, start_date, end_date, rows_affected),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_latest_date(conn: sqlite3.Connection) -> str | None:
    """
    Return the most recent date stored in the prices table, or None if
    the table is empty.
    """
    row = conn.execute("SELECT MAX(date) FROM prices").fetchone()
    return row[0] if row else None


def get_earliest_date(conn: sqlite3.Connection) -> str | None:
    """Return the oldest date stored, or None if the table is empty."""
    row = conn.execute("SELECT MIN(date) FROM prices").fetchone()
    return row[0] if row else None


def get_price_range(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """
    Fetch all price rows between start_date and end_date (both inclusive).
    Rows are returned sorted by date ascending.

    Args:
        start_date: YYYY-MM-DD string.
        end_date:   YYYY-MM-DD string.

    Returns:
        List of dicts with keys: date, open, high, low, close, volume, source.
    """
    cursor = conn.execute(
        """
        SELECT date, open, high, low, close, volume, source
        FROM   prices
        WHERE  date BETWEEN ? AND ?
        ORDER  BY date ASC
        """,
        (start_date, end_date),
    )
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_row_count(conn: sqlite3.Connection) -> int:
    """Total number of rows in the prices table."""
    row = conn.execute("SELECT COUNT(*) FROM prices").fetchone()
    return row[0]


def get_missing_dates(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> list[str]:
    """
    Return a sorted list of YYYY-MM-DD strings that fall within
    [start_date, end_date] but are absent from the prices table.

    Useful for detecting non-contiguous gaps and deciding whether a
    backfill is needed.
    """
    # Build the full expected date sequence in Python — SQLite doesn't have
    # a built-in date sequence generator.
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    expected: set[str] = set()
    cursor = start
    while cursor <= end:
        expected.add(cursor.isoformat())
        cursor += timedelta(days=1)

    # Fetch what we actually have.
    db_rows = conn.execute(
        "SELECT date FROM prices WHERE date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchall()
    present = {row[0] for row in db_rows}

    return sorted(expected - present)


def get_cache_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Return a summary dict describing the current state of the price cache.
    Intended for diagnostics and the --status flag in the fetch script.
    """
    total = get_row_count(conn)
    earliest = get_earliest_date(conn)
    latest = get_latest_date(conn)

    gaps: list[str] = []
    if earliest and latest:
        gaps = get_missing_dates(conn, earliest, latest)

    # Count rows by source.
    source_counts: dict[str, int] = {}
    for row in conn.execute(
        "SELECT source, COUNT(*) FROM prices GROUP BY source"
    ).fetchall():
        source_counts[row[0]] = row[1]

    return {
        "total_rows":    total,
        "earliest_date": earliest,
        "latest_date":   latest,
        "gap_count":     len(gaps),
        "gaps":          gaps[:20],        # truncate for display
        "rows_by_source": source_counts,
    }

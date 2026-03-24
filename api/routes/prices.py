"""
GET /prices

Returns the full OHLCV price series from the local SQLite cache.
Used by the frontend chart to render the candlestick baseline.

Optional query parameters:
    start   YYYY-MM-DD   Earliest date to include (default: earliest in DB)
    end     YYYY-MM-DD   Latest  date to include  (default: latest  in DB)
"""

from fastapi import APIRouter, HTTPException, Query

from api.deps import DbConn
from db.database import get_cache_status, get_price_range

router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("")
def get_prices(
    conn: DbConn,
    start: str | None = Query(default=None, description="Start date YYYY-MM-DD"),
    end:   str | None = Query(default=None, description="End date YYYY-MM-DD"),
):
    """
    Return OHLCV rows between `start` and `end` (both inclusive).

    If `start` / `end` are omitted the full cached history is returned.
    Dates outside the cached range are silently clipped to the available
    extent rather than returning an error.
    """
    status = get_cache_status(conn)

    if status["total_rows"] == 0:
        raise HTTPException(
            status_code=503,
            detail="No price data available. Run scripts/fetch_prices.py first.",
        )

    earliest = status["earliest_date"]
    latest   = status["latest_date"]

    # Clip requested range to what we actually have.
    start_date = max(start, earliest) if start else earliest
    end_date   = min(end,   latest)   if end   else latest

    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail=f"start ({start_date}) is after end ({end_date}).",
        )

    rows = get_price_range(conn, start_date, end_date)

    return {
        "start":  start_date,
        "end":    end_date,
        "count":  len(rows),
        "prices": rows,
    }


@router.get("/status")
def get_price_status(conn: DbConn):
    """Return a summary of the current price cache (row count, date range, gaps)."""
    return get_cache_status(conn)

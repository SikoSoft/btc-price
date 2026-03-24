"""
GET  /news/{anomaly_id}         — Top articles for one anomaly (from cache)
POST /news/{anomaly_id}/fetch   — Trigger a fresh GDELT fetch for one anomaly
POST /news/fetch-all            — Fetch news for all anomalies under a config hash
"""

import sqlite3

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from api.deps import DbConn
from config import (
    GDELT_MAX_RETRIES,
    GDELT_SLEEP_SECONDS,
    GDELT_TIMEOUT,
    NEWS_TOP_N,
    NEWS_WINDOW_DAYS,
    default_analysis_config,
)
from db.database import (
    get_anomalies,
    get_cache_status,
    get_news_for_anomaly,
    get_price_range,
    upsert_anomalies,
)
from analysis.metrics import to_dataframe
from analysis.scoring import hash_config, run_all
from news.aggregator import NewsAggregator
from news.providers.gdelt import GDELTProvider
from news.sources import NEWS_SOURCES

router = APIRouter(prefix="/news", tags=["news"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_aggregator(conn: sqlite3.Connection) -> NewsAggregator:
    provider = GDELTProvider(
        sleep_seconds=GDELT_SLEEP_SECONDS,
        max_retries=GDELT_MAX_RETRIES,
        timeout=GDELT_TIMEOUT,
    )
    return NewsAggregator(
        conn,
        provider,
        NEWS_SOURCES,
        window_days=NEWS_WINDOW_DAYS,
        top_n=NEWS_TOP_N,
        sleep_between=GDELT_SLEEP_SECONDS,
    )


def _get_anomaly_or_404(conn: sqlite3.Connection, anomaly_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM anomalies WHERE id = ?", (anomaly_id,)
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Anomaly '{anomaly_id}' not found. "
                   "Run POST /anomalies first to detect and cache anomalies.",
        )
    return dict(row)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class FetchAllRequest(BaseModel):
    config_hash:   str | None = None   # if None, uses default config
    force_refresh: bool       = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{anomaly_id}")
def get_news(anomaly_id: str, conn: DbConn):
    """
    Return cached news articles for a single anomaly.

    Articles are served from the SQLite cache — no outbound HTTP.
    If the anomaly hasn't had news fetched yet, an empty list is returned
    with `fetched` = false, signalling the frontend to trigger a fetch.
    """
    anomaly  = _get_anomaly_or_404(conn, anomaly_id)
    articles = get_news_for_anomaly(conn, anomaly_id)

    return {
        "anomaly_id":    anomaly_id,
        "anomaly_date":  anomaly["date"],
        "anomaly_type":  anomaly["type"],
        "fetched":       anomaly["news_fetched_at"] is not None,
        "fetched_at":    anomaly["news_fetched_at"],
        "article_count": len(articles),
        "articles":      articles,
    }


@router.post("/{anomaly_id}/fetch")
def fetch_news_for_anomaly(
    anomaly_id:     str,
    conn:           DbConn,
    force_refresh:  bool = False,
):
    """
    Fetch (or re-fetch) news for a single anomaly from GDELT.

    This is a synchronous call — it blocks until the GDELT request
    completes (typically < 10 seconds including rate-limit sleep).
    Use force_refresh=true to re-fetch even if articles are already cached.
    """
    anomaly    = _get_anomaly_or_404(conn, anomaly_id)
    aggregator = _make_aggregator(conn)

    enriched = aggregator.run(
        [anomaly],
        force_refresh=force_refresh,
    )

    articles = enriched[0]["articles"] if enriched else []
    return {
        "anomaly_id":    anomaly_id,
        "article_count": len(articles),
        "articles":      articles,
    }


@router.post("/fetch-all")
def fetch_all_news(body: FetchAllRequest, conn: DbConn):
    """
    Fetch news for every anomaly under a given config hash.

    If `config_hash` is omitted, the default analysis config is used —
    running detection if no anomalies are cached for it yet.

    This call is synchronous and may take several minutes for 30 anomalies
    (GDELT rate limit: 1 request / 5 seconds).  For a non-blocking version,
    use the background task endpoint POST /news/fetch-all/background instead.

    Returns a summary; individual articles are retrievable via
    GET /news/{anomaly_id}.
    """
    # Resolve or recompute config hash.
    if body.config_hash:
        cfg_hash = body.config_hash
        anomalies = get_anomalies(conn, cfg_hash)
        if not anomalies:
            raise HTTPException(
                status_code=404,
                detail=f"No anomalies found for config_hash '{cfg_hash}'. "
                       "POST /anomalies first.",
            )
    else:
        cfg      = default_analysis_config()
        cfg_hash = hash_config(cfg)
        anomalies = get_anomalies(conn, cfg_hash)

        if not anomalies:
            # Run detection, then fetch news.
            status = get_cache_status(conn)
            if status["total_rows"] == 0:
                raise HTTPException(
                    status_code=503,
                    detail="No price data. Run scripts/fetch_prices.py first.",
                )
            rows    = get_price_range(conn, status["earliest_date"], status["latest_date"])
            df      = to_dataframe(rows)
            results = run_all(df, cfg)
            anomalies = (
                results["reversals"]
                + results["amplifications"]
                + results["stagnations"]
            )
            upsert_anomalies(conn, anomalies)

    aggregator = _make_aggregator(conn)
    enriched   = aggregator.run(
        list(anomalies),
        force_refresh=body.force_refresh,
    )

    total_articles = sum(len(a.get("articles", [])) for a in enriched)
    fetched_count  = sum(1 for a in enriched if a.get("articles"))

    return {
        "config_hash":     cfg_hash,
        "anomaly_count":   len(enriched),
        "with_articles":   fetched_count,
        "total_articles":  total_articles,
        "summary": [
            {
                "anomaly_id":    a["id"],
                "date":          a["date"],
                "type":          a["type"],
                "article_count": len(a.get("articles", [])),
            }
            for a in enriched
        ],
    }

"""
News aggregator for bitcoin_analyzer.

Responsibilities
----------------
1. Accept a list of anomaly dicts (from analysis.scoring.run_all).
2. Persist them to the anomalies table (keyed by config_hash).
3. For each anomaly, check whether news has already been fetched.
4. If not, query the news provider for the window before the anomaly date.
5. Store the top-N articles in news_articles.
6. Return the full result: anomalies with their associated articles.

Cache behaviour
---------------
An anomaly's news_fetched_at column is set when we attempt a fetch.
Even an empty result is cached (GDELT has limited historical coverage).
Re-fetching is only triggered by passing force_refresh=True.

Public API
----------
    from news.aggregator import NewsAggregator
    from news.providers.gdelt import GDELTProvider
    from news.sources import NEWS_SOURCES

    agg = NewsAggregator(conn, GDELTProvider(), NEWS_SOURCES)
    results = agg.run(anomaly_dicts)       # fetch + cache all news
    articles = agg.get_articles(anomaly_id)  # read from cache
"""

import hashlib
import sqlite3
import time
from datetime import date, datetime, timezone

from db.database import (
    get_anomalies,
    get_news_for_anomaly,
    mark_news_fetched,
    upsert_anomalies,
    upsert_news_articles,
)
from news.providers.base import NewsProvider


class NewsAggregator:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: NewsProvider,
        sources: list[dict],
        window_days: int = 3,
        top_n: int = 10,
        sleep_between: float = 0.5,
    ) -> None:
        """
        Parameters
        ----------
        conn            Open SQLite connection (caller owns lifecycle).
        provider        A NewsProvider implementation (e.g. GDELTProvider).
        sources         List of {"name": str, "domain": str} dicts.
        window_days     Days before the anomaly to search for news.
        top_n           Maximum articles to store per anomaly.
        sleep_between   Seconds to sleep between provider calls.
        """
        self._conn          = conn
        self._provider      = provider
        self._sources       = sources
        self._window_days   = window_days
        self._top_n         = top_n
        self._sleep         = sleep_between

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        anomaly_dicts: list[dict],
        force_refresh: bool = False,
        progress_callback=None,
    ) -> list[dict]:
        """
        Persist anomalies and fetch + cache news for each one.

        Parameters
        ----------
        anomaly_dicts     Output of analysis.scoring.run_all() flattened to
                          a single list across all three categories, or the
                          full dict with "reversals"/"amplifications"/
                          "stagnations" keys — both forms are accepted.
        force_refresh     Re-fetch news even if already cached.
        progress_callback Optional callable(current, total, anomaly_id) for
                          progress reporting.

        Returns
        -------
        List of anomaly dicts, each enriched with an "articles" key
        containing up to `top_n` article dicts.
        """
        flat = self._flatten(anomaly_dicts)
        if not flat:
            return []

        # Persist anomaly rows (upsert is idempotent).
        upsert_anomalies(self._conn, flat)

        total   = len(flat)
        results = []

        for i, anomaly in enumerate(flat):
            if progress_callback:
                progress_callback(i + 1, total, anomaly["id"])

            articles = self._get_or_fetch(anomaly, force_refresh)
            results.append({**anomaly, "articles": articles})

            # Polite pause between provider calls.
            if i < total - 1:
                time.sleep(self._sleep)

        return results

    def get_articles(self, anomaly_id: str) -> list[dict]:
        """Read cached articles for one anomaly from the DB."""
        return get_news_for_anomaly(self._conn, anomaly_id)

    def get_cached_anomalies(self, config_hash: str) -> list[dict]:
        """Return all anomalies stored for a given config hash."""
        return get_anomalies(self._conn, config_hash)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flatten(self, anomaly_data) -> list[dict]:
        """
        Accept either a flat list or the run_all() output dict and return
        a plain list of anomaly dicts.
        """
        if isinstance(anomaly_data, list):
            return anomaly_data
        # run_all() returns {"reversals": [...], "amplifications": [...], ...}
        flat = []
        for key in ("reversals", "amplifications", "stagnations"):
            flat.extend(anomaly_data.get(key, []))
        return flat

    def _get_or_fetch(
        self,
        anomaly: dict,
        force_refresh: bool,
    ) -> list[dict]:
        """
        Return articles for one anomaly, fetching from the provider if needed.
        """
        # If already cached and not forcing a refresh, return from DB.
        if anomaly.get("news_fetched_at") and not force_refresh:
            return get_news_for_anomaly(self._conn, anomaly["id"])

        # Also check the DB in case the in-memory dict is stale.
        if not force_refresh:
            db_rows = get_news_for_anomaly(self._conn, anomaly["id"])
            # news_fetched_at being set (even with 0 articles) means we tried.
            # Check directly in the DB to handle the "fetched but 0 results" case.
            row = self._conn.execute(
                "SELECT news_fetched_at FROM anomalies WHERE id = ?",
                (anomaly["id"],),
            ).fetchone()
            if row and row[0]:
                return db_rows

        # Fetch from provider.
        anomaly_date = date.fromisoformat(anomaly["date"])
        raw_articles = self._provider.fetch_articles(
            anomaly_date,
            self._window_days,
            self._sources,
        )

        # Keep only the top-N by relevance (already sorted by provider).
        top_articles = raw_articles[: self._top_n]

        # Persist articles.
        db_articles = [
            self._to_db_article(a, anomaly["id"])
            for a in top_articles
        ]
        upsert_news_articles(self._conn, db_articles)

        # Mark news as fetched (even if empty — we don't want to re-query).
        fetched_at = datetime.now(timezone.utc).isoformat()
        mark_news_fetched(self._conn, anomaly["id"], fetched_at)

        return db_articles

    @staticmethod
    def _to_db_article(article: dict, anomaly_id: str) -> dict:
        """
        Convert a provider article dict to the DB schema format.
        The primary key is a hash of (anomaly_id + url) to avoid duplicates.
        """
        pk = hashlib.sha1(
            f"{anomaly_id}:{article['url']}".encode()
        ).hexdigest()[:16]

        return {
            "id":            f"{anomaly_id}_{pk}",
            "anomaly_id":    anomaly_id,
            "source_name":   article.get("source_name", ""),
            "source_domain": article.get("domain", ""),
            "title":         article.get("title", ""),
            "url":           article.get("url", ""),
            "published_at":  article.get("published_at", ""),
            "relevance":     article.get("relevance", 0.0),
        }

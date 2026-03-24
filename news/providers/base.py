"""
Abstract base class for news providers.

Any concrete provider (GDELT, NewsAPI, Guardian, etc.) must implement:

    fetch_articles(anomaly_date, window_days, sources) -> list[dict]

The returned list contains article dicts with a standard schema so the
aggregator layer never has to care which provider was used.

Standard article dict keys
--------------------------
    title        str   Headline text
    url          str   Canonical article URL
    domain       str   Source domain (e.g. "reuters.com")
    source_name  str   Human label matched from sources list (e.g. "Reuters")
    published_at str   ISO-8601 date string, or empty string if unknown
    relevance    float Position-based relevance score in [0.0, 1.0]
"""

from abc import ABC, abstractmethod
from datetime import date


class NewsProvider(ABC):
    """Abstract interface for a news data source."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider, e.g. 'gdelt'."""

    @abstractmethod
    def fetch_articles(
        self,
        anomaly_date: date,
        window_days: int,
        sources: list[dict],
    ) -> list[dict]:
        """
        Fetch news articles from the given sources published in the
        `window_days` days immediately before `anomaly_date`.

        Parameters
        ----------
        anomaly_date : date
            The date of the price anomaly.  Articles are fetched from
            [anomaly_date - window_days, anomaly_date - 1] inclusive.
        window_days : int
            How many days before the anomaly to search (default 3).
        sources : list[dict]
            Each dict must have at least {"name": str, "domain": str}.

        Returns
        -------
        List of article dicts conforming to the standard schema above.
        May be empty if the provider has no coverage for that date range.
        """

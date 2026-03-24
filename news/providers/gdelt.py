"""
GDELT DOC 2.0 API news provider for bitcoin_analyzer.

GDELT (Global Database of Events, Language, and Tone) is a free, no-auth
news index that covers web articles going back to around 2013.

API reference: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

Coverage note
-------------
The GDELT DOC 2.0 API has a rolling lookback window.  In practice, the
window has been extended over time (originally 3 months, then 1 year via
the "full-year searching" update).  For anomaly dates older than the
current lookback window the API returns an empty result set — this is
treated as a cache-able "no news available" outcome, not an error.

Query strategy
--------------
We issue a single query per anomaly that combines all target domains with
boolean OR, so each anomaly requires exactly one HTTP request.  The query
template is:

    bitcoin (domain:reuters.com OR domain:bbc.co.uk OR ...)

Results are filtered client-side to the configured source domains so that
any off-domain hits GDELT may return are discarded.

Relevance scoring
-----------------
GDELT returns articles in its own relevance order.  We convert position
to a [1.0 → 0.0] float so that first place = 1.0 and last = 0.0.
"""

import sys
import time
from datetime import date, timedelta

import requests

from news.providers.base import NewsProvider


class GDELTProvider(NewsProvider):
    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    # Maximum records the GDELT API will return per request.
    _MAX_RECORDS = 250

    # GDELT enforces 1 request per 5 seconds.
    _RATE_LIMIT_SLEEP = 5.0

    def __init__(
        self,
        sleep_seconds: float = 5.0,
        max_retries: int = 3,
        timeout: int = 30,
    ) -> None:
        self._sleep = sleep_seconds
        self._max_retries = max_retries
        self._timeout = timeout

    # ------------------------------------------------------------------
    # NewsProvider interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "gdelt"

    def fetch_articles(
        self,
        anomaly_date: date,
        window_days: int,
        sources: list[dict],
    ) -> list[dict]:
        """
        Fetch bitcoin news from the configured sources in the `window_days`
        days before `anomaly_date`.

        Returns a list of article dicts (standard schema) sorted by
        relevance descending.  Returns [] when the date range is outside
        GDELT's coverage window or when no matching articles exist.
        """
        if not sources:
            return []

        end_dt   = anomaly_date - timedelta(days=1)
        start_dt = anomaly_date - timedelta(days=window_days)

        query = self._build_query(sources)
        raw   = self._request(query, start_dt, end_dt)

        # Build a fast lookup of domains we actually care about.
        # We match by suffix so that subdomains like feeds.ft.com or
        # edition.cnn.com are accepted alongside bare ft.com / cnn.com.
        source_domains  = [s["domain"].lower() for s in sources]
        domain_to_name  = {s["domain"].lower(): s["name"] for s in sources}

        def _match_domain(raw_domain: str) -> str | None:
            """Return the canonical source domain if raw_domain belongs to it."""
            d = raw_domain.lower()
            for sd in source_domains:
                if d == sd or d.endswith("." + sd):
                    return sd
            return None

        # Filter and normalise.
        articles = []
        for item in raw:
            domain     = item.get("domain", "").lower()
            canonical  = _match_domain(domain)
            if canonical is None:
                continue
            domain_clean = canonical
            articles.append({
                "title":        item.get("title", "").strip(),
                "url":          item.get("url", "").strip(),
                "domain":       domain_clean,
                "source_name":  domain_to_name.get(domain_clean, domain_clean),
                "published_at": self._parse_date(item.get("seendate", "")),
                "relevance":    0.0,  # filled in below
            })

        # Drop rows with no URL or title.
        articles = [a for a in articles if a["url"] and a["title"]]

        # Assign position-based relevance: position 0 → 1.0, last → 0.0.
        n = len(articles)
        for i, a in enumerate(articles):
            a["relevance"] = round(1.0 - (i / max(n - 1, 1)), 4) if n > 1 else 1.0

        return articles

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_query(self, sources: list[dict]) -> str:
        """
        Build the GDELT query string that targets bitcoin news across all
        configured source domains.

        Example output:
            bitcoin (domain:reuters.com OR domain:bbc.co.uk OR ...)
        """
        domain_clauses = " OR ".join(f"domain:{s['domain']}" for s in sources)
        return f"bitcoin ({domain_clauses})"

    def _request(
        self,
        query: str,
        start_dt: date,
        end_dt: date,
    ) -> list[dict]:
        """
        Execute one GDELT artlist request with retry/backoff.

        Returns the raw list of article dicts from the JSON response, or []
        on any unrecoverable error.
        """
        params = {
            "query":         query,
            "mode":          "artlist",
            "maxrecords":    self._MAX_RECORDS,
            "format":        "json",
            "sort":          "DateDesc",
            "startdatetime": start_dt.strftime("%Y%m%d000000"),
            "enddatetime":   end_dt.strftime("%Y%m%d235959"),
        }

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.get(
                    self.BASE_URL,
                    params=params,
                    timeout=self._timeout,
                )

                # 429 = rate limited; honour the hard 5-second rule then
                # add exponential backoff on top.
                if resp.status_code == 429:
                    wait = self._RATE_LIMIT_SLEEP * (2 ** (attempt - 1))
                    print(
                        f"  [gdelt] rate-limited (429), waiting {wait:.0f}s "
                        f"(attempt {attempt}/{self._max_retries})…",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue

                resp.raise_for_status()

                # GDELT occasionally returns HTTP 200 with an empty body.
                if not resp.text.strip():
                    return []

                data = resp.json()
                return data.get("articles") or []

            except requests.exceptions.Timeout:
                print(
                    f"  [gdelt] timeout on attempt {attempt}/{self._max_retries}",
                    file=sys.stderr,
                )
                if attempt == self._max_retries:
                    return []
                time.sleep(attempt * 2)

            except requests.exceptions.RequestException as exc:
                print(f"  [gdelt] request error: {exc}", file=sys.stderr)
                if attempt == self._max_retries:
                    return []
                time.sleep(attempt * 2)

            except (ValueError, KeyError) as exc:
                # Malformed JSON or unexpected structure.
                print(f"  [gdelt] parse error: {exc}", file=sys.stderr)
                return []

        print(
            f"  [gdelt] gave up after {self._max_retries} attempts",
            file=sys.stderr,
        )
        return []

    @staticmethod
    def _parse_date(raw: str) -> str:
        """
        Convert a GDELT seendate string to ISO-8601 (YYYY-MM-DD).

        GDELT uses 'YYYYMMDDTHHMMSSZ' or plain 'YYYYMMDD' format.
        Returns empty string on parse failure.
        """
        if not raw:
            return ""
        # Strip time component if present.
        date_part = raw[:8]
        if len(date_part) == 8 and date_part.isdigit():
            return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
        return ""

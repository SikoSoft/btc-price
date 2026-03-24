"""
Configurable list of news sources for bitcoin_analyzer.

Each entry is a dict with:
    name    str   Human-readable label shown in the UI
    domain  str   Domain passed to the GDELT query filter

To add a new source, append one dict to NEWS_SOURCES.  No other code needs
to change — the provider and aggregator read this list at runtime.
"""

NEWS_SOURCES: list[dict] = [
    {"name": "Reuters",         "domain": "reuters.com"},
    {"name": "BBC",             "domain": "bbc.co.uk"},
    {"name": "CNN",             "domain": "cnn.com"},
    {"name": "Fox News",        "domain": "foxnews.com"},
    {"name": "Financial Times", "domain": "ft.com"},
    {"name": "CoinDesk",        "domain": "coindesk.com"},
]

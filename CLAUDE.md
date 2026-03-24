# bitcoin_analyzer — Project Context

## What this project is

A set of Python tools for Bitcoin price analysis. The end goal is a web interface showing a candlestick chart with 30 "price anomalies" marked on it. Clicking an anomaly shows the top 10 aggregated news stories from the 3 days before it occurred. The hypothesis: correlate real-world events with price movements to inform future predictions.

## Architecture

```
bitcoin_analyzer/
├── config.py                  # All constants, thresholds, env-var overrides
├── db/
│   └── database.py            # SQLite schema + upsert_prices, get_price_range, etc.
├── data/
│   ├── cache.py               # "Fetch only what's missing" incremental logic
│   └── providers/
│       ├── base.py            # Abstract BaseProvider (fetch_range, fetch_recent)
│       ├── bitfinex.py        # DEFAULT — no auth, full OHLCV, 2013–present
│       ├── coingecko.py       # Alternative — requires free Demo API key
│       ├── kraken.py          # Alternative — no key, but hard-capped at 720 days
│       └── __init__.py        # get_provider("bitfinex") factory
├── scripts/
│   └── fetch_prices.py        # CLI: --status, --provider, --start-date, --end-date, --force-refresh
├── analysis/                  # NOT YET BUILT — next layer
│   ├── metrics.py             # Velocity, momentum, volatility calculations
│   ├── anomalies.py           # Reversal, amplification, stagnation detection
│   └── scoring.py             # Rank & select top 10 per category
├── news/                      # NOT YET BUILT
│   ├── providers/
│   │   ├── base.py
│   │   └── gdelt.py           # GDELT Project — free, no key, back to 2013
│   ├── sources.py             # Configurable list of news domains
│   └── aggregator.py         # Fetch & cache top 10 stories per anomaly
├── api/                       # NOT YET BUILT
│   ├── app.py                 # FastAPI
│   └── routes/
│       ├── anomalies.py       # POST /anomalies {config} → run detection
│       ├── news.py            # GET /news/{anomaly_id}
│       └── prices.py          # GET /prices
└── web/                       # NOT YET BUILT
    ├── index.html
    ├── chart.js               # TradingView Lightweight Charts
    ├── controls.js            # Parameter UI + loading states
    └── styles.css
```

## What has been built (Layer 1 complete)

- Full price data pipeline operational
- Bitfinex provider: 4,706 rows of daily OHLCV, 2013-03-31 to present, single HTTP call, no auth
- SQLite DB (`bitcoin_analyzer.db`) populated and verified
- Incremental cache logic: only fetches dates not already in DB
- CLI script working: `scripts/fetch_prices.py`
- 7 gap dates around Aug 2–9 2016 are expected (Bitfinex hack/trading suspension)
- CoinGecko kept as optional provider but dropped as default (now requires key even for free tier)

## Price anomaly types (3 categories, top 10 each = 30 total)

- **Reversals** — sudden change in direction. Score = absolute difference between backward and forward N-day momentum where sign flips.
- **Amplifications** — sudden increase in same direction (acceleration). Score = forward minus backward momentum where sign is the same.
- **Stagnations** — most quiet/flat periods. Score = inverted rolling volatility (low vol = high score). Returns a date range, not a point.

All detection functions take a `pd.DataFrame` of prices + a config dict, return a scored DataFrame. Fully stateless/pure so they're easy to re-run when parameters change.

## Config hash caching

Anomaly results will be keyed by a hash of the config used to generate them. This avoids re-running expensive detection when parameters haven't changed. The `anomalies` table has a `config_hash` column for this purpose.

## SQLite schema (planned)

```sql
CREATE TABLE price_data (
    date    TEXT PRIMARY KEY,
    open    REAL, high REAL, low REAL, close REAL, volume REAL
);

CREATE TABLE anomalies (
    id          TEXT PRIMARY KEY,   -- e.g. "reversal_2017-12-17"
    type        TEXT,               -- 'reversal' | 'amplification' | 'stagnation'
    date        TEXT,
    score       REAL,
    config_hash TEXT,
    metadata    TEXT                -- JSON blob
);

CREATE TABLE news_articles (
    id           TEXT PRIMARY KEY,
    anomaly_id   TEXT REFERENCES anomalies(id),
    source       TEXT,
    title        TEXT,
    url          TEXT,
    published_at TEXT,
    relevance    REAL
);
```

## News sources (configurable list in news/sources.py)

Reuters, BBC, CNN, Fox News, Financial Times, CoinDesk — via GDELT Project API.

## Key decisions

- **Bitfinex as default provider** — no auth, genuine OHLCV (not just close+volume), full history in one request
- **GDELT for news** — only free option with historical coverage back to 2013
- **Abstract provider interfaces** — swap data sources without touching analysis code
- **FastAPI** — async support for parallel news fetching across 30 anomalies
- **TradingView Lightweight Charts** — purpose-built financial charting library
- **SQLite** — zero infrastructure, sufficient for this scale

## Next step

Build `analysis/` layer:
1. `analysis/metrics.py` — rolling momentum, volatility, ATR helpers
2. `analysis/anomalies.py` — reversal, amplification, stagnation detectors
3. `analysis/scoring.py` — rank and select top 10 per category

All functions should accept `pd.DataFrame` + config dict, return scored DataFrame.

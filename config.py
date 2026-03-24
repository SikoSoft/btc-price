"""
Central configuration for bitcoin_analyzer.

All tuneable values live here. They can be overridden via environment
variables (e.g. export BTC_DB_PATH=/data/prices.db) or by editing the
defaults directly.  No third-party config library is used so the module
has zero extra dependencies.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Root of the project — used to anchor relative paths.
PROJECT_ROOT = Path(__file__).parent

# SQLite database file.  Override with env var BTC_DB_PATH.
DB_PATH: str = os.environ.get(
    "BTC_DB_PATH",
    str(PROJECT_ROOT / "bitcoin_analyzer.db"),
)

# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

# Which provider to use by default.
# Options: "coingecko" | "kraken"
DEFAULT_PROVIDER: str = os.environ.get("BTC_DEFAULT_PROVIDER", "bitfinex")

# ---------------------------------------------------------------------------
# CoinGecko
# ---------------------------------------------------------------------------

# Public base URL (no key required, rate-limited to ~30 req/min).
# When a paid Pro key is set the base URL switches automatically — see
# the provider implementation.
COINGECKO_BASE_URL: str = "https://api.coingecko.com/api/v3"
COINGECKO_PRO_BASE_URL: str = "https://pro-api.coingecko.com/api/v3"

# Optional API key.  Register for free at coingecko.com to get a Demo key
# that raises the rate limit to 30 stable calls/min.
# Demo keys start with "CG-"; Pro keys are longer hex strings.
COINGECKO_API_KEY: str | None = os.environ.get("COINGECKO_API_KEY")

# Conservative sleep between CoinGecko calls to stay well within rate limits.
COINGECKO_SLEEP_SECONDS: float = float(
    os.environ.get("COINGECKO_SLEEP_SECONDS", "2.0")
)

# Number of times to retry a failed request before giving up.
COINGECKO_MAX_RETRIES: int = int(os.environ.get("COINGECKO_MAX_RETRIES", "4"))

# Coin identifier on CoinGecko.
COINGECKO_COIN_ID: str = "bitcoin"

# Quote currency.
COINGECKO_VS_CURRENCY: str = "usd"

# ---------------------------------------------------------------------------
# Kraken
# ---------------------------------------------------------------------------

KRAKEN_BASE_URL: str = "https://api.kraken.com/0/public"

# Kraken trading pair name.  Note: Kraken normalises the response key to
# the canonical form ("XXBTZUSD") regardless of what you send, so the
# provider code resolves the key dynamically.
KRAKEN_PAIR: str = "XBTUSD"

# Daily candle interval in minutes.
KRAKEN_INTERVAL_MINUTES: int = 1440

# Kraken returns at most 720 candles per request.
KRAKEN_MAX_CANDLES: int = 720

# Conservative sleep between Kraken calls.
KRAKEN_SLEEP_SECONDS: float = float(
    os.environ.get("KRAKEN_SLEEP_SECONDS", "1.5")
)

KRAKEN_MAX_RETRIES: int = int(os.environ.get("KRAKEN_MAX_RETRIES", "4"))

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

# Timeout (seconds) for all outbound HTTP requests.
REQUEST_TIMEOUT_SECONDS: int = int(os.environ.get("REQUEST_TIMEOUT", "30"))

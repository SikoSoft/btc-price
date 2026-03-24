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

# ---------------------------------------------------------------------------
# Anomaly detection defaults
# ---------------------------------------------------------------------------
# All values are overridable at runtime by passing a config dict to run_all().
# They are collected here so the API can expose GET /config/defaults easily.

# --- Reversals --------------------------------------------------------------
# Number of days before the candidate date used to measure prior momentum.
REVERSAL_LOOKBACK: int = int(os.environ.get("BTC_REVERSAL_LOOKBACK", "10"))
# Number of days after the candidate date used to measure subsequent momentum.
REVERSAL_LOOKFORWARD: int = int(os.environ.get("BTC_REVERSAL_LOOKFORWARD", "10"))
# Minimum score (|forward - backward| momentum) to qualify as a reversal.
REVERSAL_MIN_SCORE: float = float(os.environ.get("BTC_REVERSAL_MIN_SCORE", "0.05"))

# --- Amplifications ---------------------------------------------------------
AMPLIFICATION_LOOKBACK: int = int(
    os.environ.get("BTC_AMPLIFICATION_LOOKBACK", "10")
)
AMPLIFICATION_LOOKFORWARD: int = int(
    os.environ.get("BTC_AMPLIFICATION_LOOKFORWARD", "10")
)
AMPLIFICATION_MIN_SCORE: float = float(
    os.environ.get("BTC_AMPLIFICATION_MIN_SCORE", "0.05")
)

# --- Stagnations ------------------------------------------------------------
# Rolling window (days) used to compute volatility.
STAGNATION_WINDOW: int = int(os.environ.get("BTC_STAGNATION_WINDOW", "30"))
# Minimum normalised score [0–1] to qualify as a stagnation candidate.
STAGNATION_MIN_SCORE: float = float(
    os.environ.get("BTC_STAGNATION_MIN_SCORE", "0.0")
)

# --- Common -----------------------------------------------------------------
# Number of anomalies to return per category (3 × top_n = total markers).
TOP_N: int = int(os.environ.get("BTC_TOP_N", "10"))


# ---------------------------------------------------------------------------
# News / GDELT
# ---------------------------------------------------------------------------

# Number of days before an anomaly to search for related news.
NEWS_WINDOW_DAYS: int = int(os.environ.get("BTC_NEWS_WINDOW_DAYS", "3"))

# Maximum articles to store per anomaly.
NEWS_TOP_N: int = int(os.environ.get("BTC_NEWS_TOP_N", "10"))

# Seconds to sleep between GDELT requests to avoid rate-limiting.
# GDELT enforces a hard limit of 1 request per 5 seconds.
GDELT_SLEEP_SECONDS: float = float(
    os.environ.get("BTC_GDELT_SLEEP_SECONDS", "5.0")
)

# Retry attempts for failed GDELT requests.
GDELT_MAX_RETRIES: int = int(os.environ.get("BTC_GDELT_MAX_RETRIES", "3"))

# HTTP timeout for GDELT requests (seconds).
GDELT_TIMEOUT: int = int(os.environ.get("BTC_GDELT_TIMEOUT", "30"))


def default_analysis_config() -> dict:
    """
    Return a config dict populated from the module-level constants above.
    Pass this to analysis.scoring.run_all() to use the current defaults.
    """
    return {
        "reversal_lookback":       REVERSAL_LOOKBACK,
        "reversal_lookforward":    REVERSAL_LOOKFORWARD,
        "reversal_min_score":      REVERSAL_MIN_SCORE,
        "amplification_lookback":  AMPLIFICATION_LOOKBACK,
        "amplification_lookforward": AMPLIFICATION_LOOKFORWARD,
        "amplification_min_score": AMPLIFICATION_MIN_SCORE,
        "stagnation_window":       STAGNATION_WINDOW,
        "stagnation_min_score":    STAGNATION_MIN_SCORE,
        "top_n":                   TOP_N,
    }

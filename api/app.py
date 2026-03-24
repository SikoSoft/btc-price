"""
bitcoin_analyzer FastAPI application.

Start the server:
    uvicorn api.app:app --reload --port 8000

Interactive docs:
    http://localhost:8000/docs
    http://localhost:8000/redoc

Endpoints
---------
    GET  /prices                       Full OHLCV series (chart data)
    GET  /prices/status                Cache summary (row count, date range)
    POST /anomalies                    Run detection; returns 30 anomalies
    GET  /anomalies/cached             List configs with cached results
    GET  /news/{anomaly_id}            Cached articles for one anomaly
    POST /news/{anomaly_id}/fetch      Fetch/refresh news for one anomaly
    POST /news/fetch-all               Fetch news for all anomalies
    GET  /config/defaults              Default analysis parameters
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import anomalies, config, news, prices

app = FastAPI(
    title="bitcoin_analyzer",
    description=(
        "Bitcoin price anomaly detection and historical news correlation. "
        "Detects the 10 strongest reversals, amplifications, and stagnations "
        "in BTC price history and surfaces the top news stories preceding each."
    ),
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS — allow the local web frontend to call the API from the browser.
# Tighten origins before any public deployment.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(prices.router)
app.include_router(anomalies.router)
app.include_router(news.router)
app.include_router(config.router)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/", tags=["meta"])
def root():
    return {
        "service": "bitcoin_analyzer",
        "docs":    "/docs",
        "status":  "ok",
    }

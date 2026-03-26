# BTC Price Analyzer

Utility for analyzing historic price data for Bitcoin and detecting anomalies, while providing news from the days leading up to the anomaly as context for these periods.

## Running

Run the server:

`.venv/bin/uvicorn api.app:app --reload --port 8000`

Run the front-end:

`python3 -m http.server 3000`

"""
GET /config/defaults

Returns the current default analysis parameters so the frontend can
populate its controls panel on first load without hardcoding values.
"""

from fastapi import APIRouter

from config import NEWS_WINDOW_DAYS, NEWS_TOP_N, default_analysis_config
from news.sources import NEWS_SOURCES

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/defaults")
def get_defaults():
    """
    Return the default anomaly-detection config and news settings.

    The frontend uses this to pre-populate all slider / input controls.
    The same dict can be POSTed back to /anomalies to run detection with
    the defaults, or with individual fields modified.
    """
    cfg = default_analysis_config()
    return {
        "analysis":     cfg,
        "news": {
            "window_days": NEWS_WINDOW_DAYS,
            "top_n":       NEWS_TOP_N,
        },
        "sources": NEWS_SOURCES,
    }

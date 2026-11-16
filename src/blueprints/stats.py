"""Aggregated refresh stats endpoint (GET /api/stats).

Returns rolling refresh aggregates over three time windows:
  - last_1h   (last 3 600 seconds)
  - last_24h  (last 86 400 seconds)
  - last_7d   (last 604 800 seconds)

Each window contains:
    total, success, failure, success_rate,
    p50_duration_ms, p95_duration_ms, top_failing

All three windows come from one scan of the history sidecars. The result is
cached in-process for 60 seconds (handled by compute_stats_windows) and the
response carries Cache-Control: public, max-age=60.
"""

from __future__ import annotations

import logging
from typing import cast

from flask import Blueprint, jsonify
from flask.typing import ResponseReturnValue

from blueprints._deps import get_device_config
from schemas.responses import RefreshStatsResponse, RefreshStatsWindow
from utils.api_responses import json_error
from utils.refresh_stats import compute_stats_windows

logger = logging.getLogger(__name__)

stats_bp = Blueprint("stats", __name__)

_WINDOWS = {
    "last_1h": 3_600,
    "last_24h": 86_400,
    "last_7d": 604_800,
}


@stats_bp.route("/api/stats", methods=["GET"])
def refresh_stats() -> ResponseReturnValue:
    """Return aggregated refresh statistics for 1h, 24h, and 7d windows."""
    history_dir = get_device_config().history_image_dir

    try:
        windows = compute_stats_windows(history_dir, _WINDOWS)
        payload: RefreshStatsResponse = {
            "last_1h": cast(RefreshStatsWindow, windows["last_1h"]),
            "last_24h": cast(RefreshStatsWindow, windows["last_24h"]),
            "last_7d": cast(RefreshStatsWindow, windows["last_7d"]),
        }
    except Exception:
        logger.exception("Failed to compute refresh stats")
        return json_error("failed to compute stats", status=500)

    response = jsonify(payload)
    response.headers["Cache-Control"] = "public, max-age=60"
    return response, 200

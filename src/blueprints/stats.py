"""Aggregated refresh stats endpoint (GET /api/stats).

Returns rolling refresh aggregates over three time windows:
  - last_1h   (last 3 600 seconds)
  - last_24h  (last 86 400 seconds)
  - last_7d   (last 604 800 seconds)

Each window contains:
    total, success, failure, success_rate,
    p50_duration_ms, p95_duration_ms, top_failing

Results are cached in-process for 60 seconds (handled by compute_stats) and
the response carries Cache-Control: public, max-age=60.
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify

from utils.refresh_stats import compute_stats

logger = logging.getLogger(__name__)

stats_bp = Blueprint("stats", __name__)

_WINDOW_1H = 3_600
_WINDOW_24H = 86_400
_WINDOW_7D = 604_800


@stats_bp.route("/api/stats", methods=["GET"])
def refresh_stats():
    """Return aggregated refresh statistics for 1h, 24h, and 7d windows."""
    device_config = current_app.config.get("DEVICE_CONFIG")
    history_dir: str = getattr(device_config, "history_image_dir", "")

    try:
        payload = {
            "last_1h": compute_stats(history_dir, _WINDOW_1H),
            "last_24h": compute_stats(history_dir, _WINDOW_24H),
            "last_7d": compute_stats(history_dir, _WINDOW_7D),
        }
    except Exception:
        logger.exception("Failed to compute refresh stats")
        return jsonify({"error": "failed to compute stats"}), 500

    response = jsonify(payload)
    response.headers["Cache-Control"] = "public, max-age=60"
    return response, 200

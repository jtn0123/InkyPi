"""Health check endpoints extracted from inkypi.py (JTN-289)."""

from __future__ import annotations

from flask import Flask


def register_health_endpoints(app: Flask) -> None:
    """Register /healthz (always-OK liveness) and /readyz (refresh-task readiness)."""

    @app.route("/healthz", methods=["GET"])  # type: ignore
    def healthz() -> tuple[str, int]:
        return ("OK", 200)

    @app.route("/readyz", methods=["GET"])  # type: ignore
    def readyz() -> tuple[str, int]:
        try:
            rt = app.config.get("REFRESH_TASK")
            web_only = bool(app.config.get("WEB_ONLY"))
            if web_only:
                return ("ready:web-only", 200)
            if rt and getattr(rt, "running", False):
                return ("ready", 200)
            return ("not-ready", 503)
        except Exception:
            return ("not-ready", 503)

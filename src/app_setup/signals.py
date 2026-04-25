"""Signal handler installation extracted from inkypi.py (JTN-289)."""

from __future__ import annotations

import logging
import signal

from flask import Flask, Response
from werkzeug.serving import is_running_from_reloader

logger = logging.getLogger(__name__)


def setup_signal_handlers(app: Flask) -> None:
    """Install SIGTERM/SIGINT handlers that gracefully stop the refresh task."""
    if is_running_from_reloader():
        return

    def _shutdown_handler(signum: int, frame: object | None) -> None | Response:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down gracefully", sig_name)
        rt = app.config.get("REFRESH_TASK")
        if rt is not None:
            rt.stop()
        try:
            from utils.http_client import close_http_session

            close_http_session()
        except Exception:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

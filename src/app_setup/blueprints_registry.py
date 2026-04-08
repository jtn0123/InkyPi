"""Blueprint registration extracted from inkypi.py (JTN-289)."""

from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    """Register all InkyPi Flask blueprints."""
    from blueprints.api_docs import api_docs_bp
    from blueprints.apikeys import apikeys_bp
    from blueprints.auth import auth_bp
    from blueprints.history import history_bp
    from blueprints.main import main_bp
    from blueprints.metrics import metrics_bp
    from blueprints.playlist import playlist_bp
    from blueprints.plugin import plugin_bp
    from blueprints.settings import settings_bp
    from blueprints.stats import stats_bp
    from blueprints.version_info import version_info_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(apikeys_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(plugin_bp)
    app.register_blueprint(playlist_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(api_docs_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(version_info_bp)

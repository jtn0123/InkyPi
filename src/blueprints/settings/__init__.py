"""Settings blueprint: the blueprint object and its route modules.

The routes are split across the ``_*.py`` modules below. The work behind them
lives in plain modules they import directly: ``services.updates`` (update and
rollback runner), ``services.logs`` (journal reads) and
``services.version_check`` (GitHub release check).
"""

import logging

from flask import Blueprint

# Shared by every route module so their records keep the ``blueprints.settings``
# logger name.
logger = logging.getLogger(__name__)
settings_bp: Blueprint = Blueprint("settings", __name__)

# ---------------------------------------------------------------------------
# Route handlers are split into sub-modules for maintainability.
# Import them here so they register their routes on settings_bp.
# ---------------------------------------------------------------------------
from . import _benchmarks, _config, _health, _logs, _system, _updates  # noqa: E402,F401

__all__ = ["settings_bp"]

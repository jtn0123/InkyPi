"""Shared state for the ``playlist`` blueprint package.

Holds the :data:`playlist_bp` blueprint object, the package logger, the
shared string constants and the request-model error helper that more than
one route module uses.
"""

import logging
from typing import Any

from flask import Blueprint

from utils.http_utils import json_error
from utils.request_models import CODE_VALIDATION, RequestModelError

# Both names are pinned to the pre-split module path ``blueprints.playlist``
# so log records keep their logger name (log filters and caplog-based tests
# key on it) and the blueprint keeps the same import_name. The blueprint has
# no template/static folder, so its root_path is never consulted.
logger = logging.getLogger("blueprints.playlist")
playlist_bp = Blueprint("playlist", "blueprints.playlist")

# Shared string constants to avoid duplication
_CODE_VALIDATION = CODE_VALIDATION
_MSG_TIME_OVERLAP = "Playlist time range overlaps with existing playlist"
_MSG_PLAYLIST_NOT_FOUND = "Playlist not found"

# JTN-781: the "Default" playlist is the canonical fallback shipped with the
# system and auto-created on startup when no playlists exist (see
# PlaylistManager.add_default_playlist + config bootstrap). Deleting it leaves
# the scheduler with nothing to schedule and no UI path to recreate it, so the
# server rejects the delete outright. The match is case-sensitive because every
# other code path (create, update, overlap-warning, plugin auto-add) keys off
# the exact string "Default" — a lowercase "default" is just a user-created
# playlist and is fine to delete.
DEFAULT_PLAYLIST_NAME = "Default"
_MSG_CANNOT_DELETE_DEFAULT = "Cannot delete the default playlist"


def _request_model_error_response(error: RequestModelError) -> Any:
    return json_error(
        error.message,
        status=error.status,
        code=error.code,
        details=error.details or None,
    )

"""Config schema validation utilities for InkyPi.

Provides validate_device_config() which checks a loaded device.json dict against
the bundled JSON Schema (src/config/schemas/device_config.schema.json).

On violation, raises ConfigValidationError with a human-readable message that
includes the failing field path so the user can fix it without reading a traceback.

The schema is also the one list of allowed values: the settings form reads its
enums, ranges and limits through :func:`field_rules` instead of keeping its
own copies, so the form, the saver and the loader cannot disagree.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import jsonschema

logger = logging.getLogger(__name__)

# Resolved once at import time — callers can override SCHEMA_PATH for testing.
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(_SRC_DIR, "config", "schemas", "device_config.schema.json")


class ConfigValidationError(ValueError):
    """Raised when device.json fails JSON Schema validation.

    Inherits from ValueError for backward compatibility with existing callers
    that catch ValueError.  The message always includes the failing field path
    so the user can locate the offending key without reading a Python traceback.
    """


@lru_cache(maxsize=1)
def _load_schema(schema_path: str) -> dict[str, Any]:
    """Load and cache the device config JSON Schema from *schema_path*."""
    with open(schema_path) as fh:
        return cast(dict[str, Any], json.load(fh))


def field_rules(*path: str) -> Mapping[str, Any]:
    """Return the schema for one device-config key.

    ``field_rules("image_settings", "saturation")`` is the rule for
    ``config["image_settings"]["saturation"]``. A key below a list applies to
    each of its items, so ``field_rules("playlist_config", "playlists",
    "start_time")`` is the rule for every playlist's start time. Raises
    ``KeyError`` when the schema does not describe that key, so a caller
    asking for a rule the schema lacks fails loudly instead of falling back to
    a private copy.
    """
    node: Mapping[str, Any] = _load_schema(SCHEMA_PATH)
    for key in path:
        if "properties" not in node and "items" in node:
            node = node["items"]
        node = node["properties"][key]
    return node


def allowed_values(*path: str) -> tuple[Any, ...]:
    """The ``enum`` the schema allows for one device-config key."""
    return tuple(field_rules(*path)["enum"])


def numeric_range(*path: str) -> tuple[float, float]:
    """The inclusive ``(minimum, maximum)`` the schema allows for a number."""
    rules = field_rules(*path)
    return rules["minimum"], rules["maximum"]


def default_value(*path: str) -> Any:
    """A copy of the schema's ``default`` for one device-config key.

    A copy, because the schema is cached and a caller may store the value in
    the config and change it later (``isolated_plugins`` is a list).
    """
    return deepcopy(field_rules(*path)["default"])


@lru_cache(maxsize=8)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def matches_pattern(value: str, *path: str) -> bool:
    """True when *value* satisfies the key's ``pattern``, as jsonschema checks it."""
    return _compiled(field_rules(*path)["pattern"]).search(value) is not None


def truncate_device_name(config: dict[str, Any]) -> bool:
    """Cut ``config["name"]`` to the schema's ``maxLength``, in place.

    Names saved before the cap existed (JTN-746) can be longer; the loader
    calls this before validating so such a device still starts (JTN-777), and
    the update preflight does the same so it does not refuse an update the app
    itself would load. Returns True when the name was cut. The file on disk
    keeps the long name until the next config write.
    """
    name = config.get("name")
    if not isinstance(name, str):
        return False
    try:
        max_length = field_rules("name")["maxLength"]
    except (OSError, ValueError):
        # Unreadable schema: validation is skipped too (see below).
        return False
    if len(name) <= max_length:
        return False
    logger.warning(
        "device_name_truncated: stored name is %d chars; truncating to %d "
        "(JTN-777). Re-save settings to persist the coerced value.",
        len(name),
        max_length,
    )
    config["name"] = name[:max_length]
    return True


def _format_error(ve: jsonschema.ValidationError) -> str:
    """Return a concise, path-prefixed message from a jsonschema ValidationError."""
    msg = ve.message
    if ve.path:
        msg = f"{'.'.join(str(p) for p in ve.path)}: {msg}"
    bad_repr = repr(ve.instance)
    if len(bad_repr) > 200:
        bad_repr = bad_repr[:197] + "..."
    return f"{msg} (got: {bad_repr})"


SKIPPED_PLAYLISTS_KEY = "skipped_playlists"

_PLAYLIST_TIME_LABELS = {"start_time": "start time", "end_time": "end time"}


def _describe_playlist_error(error: jsonschema.ValidationError) -> str:
    path = list(error.path)
    if len(path) == 1 and path[0] in _PLAYLIST_TIME_LABELS:
        return (
            f"{_PLAYLIST_TIME_LABELS[path[0]]} {error.instance!r} is not a time "
            "from 00:00 to 24:00"
        )
    return _format_error(error)


def playlist_label(playlist: object, index: int) -> str:
    """How messages name a playlist: its name, or its position if it has none."""
    name = playlist.get("name") if isinstance(playlist, dict) else None
    return repr(name) if isinstance(name, str) else f"#{index + 1}"


def playlist_problems(playlist: object) -> list[str]:
    """Why one stored playlist breaks the schema's playlist rules.

    Empty when it fits. This is the check for playlists that do not come
    through the playlist forms: a restored backup, and device.json when it
    loads. A bad time reads "start time '25:00' is not a time from 00:00 to
    24:00"; anything else names the field the schema rejected.
    """
    import jsonschema

    validator = jsonschema.Draft202012Validator(
        field_rules("playlist_config", "playlists")["items"]
    )
    errors = sorted(
        validator.iter_errors(playlist), key=lambda e: [str(p) for p in e.path]
    )
    # A bad time breaks the length and the pattern rule; say so once.
    return list(dict.fromkeys(_describe_playlist_error(error) for error in errors))


def set_aside_invalid_playlists(config: dict[str, Any]) -> list[str]:
    """Move the playlists that break the playlist rules out of *config*.

    The loader calls this before it validates, so one bad playlist in
    device.json (a hand edit, or a backup restored before the import checked
    playlists) is reported and skipped instead of stopping the app from
    starting. A playlist whose time can't be read would otherwise stop the
    refresh loop from choosing any playlist. Each one is kept under
    ``skipped_playlists`` with the reason, so the next config write does not
    lose its plugin settings.

    Only top-level keys of *config* are replaced, so the caller can pass a
    shallow copy. Returns one message per playlist set aside.
    """
    playlist_config = config.get("playlist_config")
    playlists = (
        playlist_config.get("playlists") if isinstance(playlist_config, dict) else None
    )
    earlier = config.get(SKIPPED_PLAYLISTS_KEY)
    if isinstance(earlier, list) and earlier:
        logger.warning(
            "device.json keeps %d playlist(s) set aside under %s; they are not "
            "shown or scheduled until fixed by hand",
            len(earlier),
            SKIPPED_PLAYLISTS_KEY,
        )
    if (
        not isinstance(playlist_config, dict)
        or not isinstance(playlists, list)
        or not os.path.isfile(SCHEMA_PATH)
    ):
        # Not a list of playlists to sort through: validation reports it.
        return []

    kept: list[Any] = []
    skipped: list[dict[str, Any]] = []
    messages: list[str] = []
    for index, playlist in enumerate(playlists):
        problems = playlist_problems(playlist)
        if not problems:
            kept.append(playlist)
            continue
        reason = "; ".join(problems)
        skipped.append({"reason": reason, "playlist": playlist})
        messages.append(f"Playlist {playlist_label(playlist, index)}: {reason}")
        logger.error(
            "playlist_set_aside: playlist %s in device.json breaks the playlist "
            "rules (%s). It is not shown or scheduled, and is kept under %s.",
            playlist_label(playlist, index),
            reason,
            SKIPPED_PLAYLISTS_KEY,
        )
    if skipped:
        config["playlist_config"] = {**playlist_config, "playlists": kept}
        config[SKIPPED_PLAYLISTS_KEY] = [
            *(earlier if isinstance(earlier, list) else []),
            *skipped,
        ]
    return messages


def validate_device_config(config_dict: dict[str, Any]) -> None:
    """Validate *config_dict* against the InkyPi device config JSON Schema.

    Validation is intentionally permissive — unknown keys are allowed so that
    old or extended configs do not break.  Only the shape and types of the
    *known* keys are enforced.

    Raises:
        ConfigValidationError: if any known field has the wrong type or value.
    """
    schema_path = SCHEMA_PATH
    if not os.path.isfile(schema_path):
        logger.warning(
            "Device config schema not found at %s; skipping validation", schema_path
        )
        return

    # Imported here, not at module level: it costs a Pi Zero ~8 MB and up to
    # 0.7 s, and render workers, which import this module through Config,
    # normally skip validation (see Config's trusted_config_digest).
    import jsonschema

    try:
        schema = _load_schema(schema_path)
        jsonschema.Draft202012Validator(schema).validate(config_dict)
    except jsonschema.ValidationError as exc:
        raise ConfigValidationError(
            f"device.json failed schema validation: {_format_error(exc)}"
        ) from exc
    except Exception as exc:
        # Any other error (e.g. schema file unreadable) — warn but do not crash.
        logger.warning("device.json validation encountered a non-fatal error: %s", exc)

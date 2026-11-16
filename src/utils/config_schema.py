"""Config schema validation utilities for InkyPi.

Provides validate_device_config() which checks a loaded device.json dict against
the bundled JSON Schema (src/config/schemas/device_config.schema.json).

On violation, raises ConfigValidationError with a human-readable message that
includes the failing field path so the user can fix it without reading a traceback.

The schema is also the one list of allowed values: the settings form reads its
enums, ranges and limits through :func:`field_rules` instead of keeping its
own copies, so the form, the saver and the loader cannot disagree.
"""

import json
import logging
import os
import re
from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
from typing import Any, cast

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
    ``config["image_settings"]["saturation"]``. Raises ``KeyError`` when the
    schema does not describe that key, so a caller asking for a rule the schema
    lacks fails loudly instead of falling back to a private copy.
    """
    node: Mapping[str, Any] = _load_schema(SCHEMA_PATH)
    for key in path:
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

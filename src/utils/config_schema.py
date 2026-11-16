"""Config schema validation utilities for InkyPi.

Provides validate_device_config() which checks a loaded device.json dict against
the bundled JSON Schema (src/config/schemas/device_config.schema.json).

On violation, raises ConfigValidationError with a human-readable message that
includes the failing field path so the user can fix it without reading a traceback.
"""

from __future__ import annotations

import json
import logging
import os
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

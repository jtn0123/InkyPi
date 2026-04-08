"""Config schema validation utilities for InkyPi.

Provides validate_device_config() which checks a loaded device.json dict against
the bundled JSON Schema (src/config/schemas/device_config.schema.json).

On violation, raises ConfigValidationError with a human-readable message that
includes the failing field path so the user can fix it without reading a traceback.
"""

import json
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Resolved once at import time — callers can override SCHEMA_PATH for testing.
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(_SRC_DIR, "config", "schemas", "device_config.schema.json")

# Module-level reference so tests can monkeypatch: e.g.
#   monkeypatch.setattr("utils.config_schema.jsonschema", None)
try:
    import jsonschema as jsonschema  # type: ignore[assignment]
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore[assignment]


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
        return json.load(fh)  # type: ignore[return-value]


def _format_error(ve: Any) -> str:
    """Return a concise, path-prefixed message from a jsonschema ValidationError."""
    msg: str = getattr(ve, "message", str(ve))
    try:
        if hasattr(ve, "path") and ve.path:
            path = ".".join(str(p) for p in ve.path)
            msg = f"{path}: {msg}"
        bad = getattr(ve, "instance", None)
        bad_repr = repr(bad)
        if len(bad_repr) > 200:
            bad_repr = bad_repr[:197] + "..."
        msg = f"{msg} (got: {bad_repr})"
    except (AttributeError, TypeError, IndexError):
        pass
    return msg


def validate_device_config(config_dict: dict[str, Any]) -> None:
    """Validate *config_dict* against the InkyPi device config JSON Schema.

    Validation is intentionally permissive — unknown keys are allowed so that
    old or extended configs do not break.  Only the shape and types of the
    *known* keys are enforced.

    Raises:
        ConfigValidationError: if any known field has the wrong type or value.
    """
    # Use the module-level jsonschema binding (patchable in tests).
    _js = jsonschema
    if _js is None:
        # Degrade gracefully: only validate orientation since that is the most
        # common user-facing mistake and doesn't require the library.
        _fallback_validate(config_dict)
        return

    schema_path = SCHEMA_PATH
    if not os.path.isfile(schema_path):
        logger.warning(
            "Device config schema not found at %s; skipping validation", schema_path
        )
        return

    try:
        schema = _load_schema(schema_path)
        _js.Draft202012Validator(schema).validate(config_dict)
    except Exception as exc:
        # Detect jsonschema.exceptions.ValidationError without a hard import.
        try:
            is_ve = hasattr(_js, "exceptions") and isinstance(
                exc, _js.exceptions.ValidationError
            )
        except (AttributeError, TypeError):
            is_ve = False

        if is_ve:
            raise ConfigValidationError(
                f"device.json failed schema validation: {_format_error(exc)}"
            ) from exc

        # Any other error (e.g. schema file unreadable) — warn but do not crash.
        logger.warning("device.json validation encountered a non-fatal error: %s", exc)


def _fallback_validate(config_dict: dict[str, Any]) -> None:
    """Minimal validation used when jsonschema is not installed."""
    if "orientation" in config_dict:
        orientation = config_dict.get("orientation")
        if orientation not in ("horizontal", "vertical"):
            raise ConfigValidationError(
                f"device.json failed schema validation: "
                f"orientation: invalid value (got: {orientation!r})"
            )

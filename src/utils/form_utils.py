"""Pure utility helpers for form input validation and sanitization.

All functions in this module are pure (no Flask imports, no request globals)
so they can be unit-tested without an application context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from html import escape
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sanitization helpers
# ---------------------------------------------------------------------------


def sanitize_log_field(value: Any, max_len: int = 200) -> str:
    """Strip control characters from a value for safe log output.

    Removes newline, carriage-return, and null bytes that would allow log
    injection, then truncates to *max_len* characters.

    Args:
        value: The value to sanitize.  Will be coerced to ``str``.
        max_len: Maximum length of the returned string (default 200).

    Returns:
        A sanitized string safe for inclusion in log messages.
    """
    text = str(value) if not isinstance(value, str) else value
    text = text.replace("\n", "").replace("\r", "").replace("\x00", "")
    return text[:max_len]


def sanitize_response_value(value: Any) -> str:
    """Sanitize a user-controlled value before reflecting it in a JSON response.

    Applies :func:`sanitize_log_field` for control-character stripping, then
    HTML-escapes the result to prevent XSS when the string is embedded in HTML
    contexts.  Angle brackets and ampersands are escaped; quotes are left
    unescaped so JSON serialisers can still handle the string normally.

    Args:
        value: The value to sanitize.  Will be coerced to ``str``.

    Returns:
        A sanitized, HTML-escaped string.
    """
    return escape(sanitize_log_field(str(value)), quote=False)


# Canonical alias so callers can use the more descriptive name.
sanitize_for_log = sanitize_log_field


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """Raised when input fails range, type, or schema validation.

    Attributes:
        message: Human-readable description of the failure.
        field: Optional field name associated with the failure.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.message = message
        self.field: str | None = field
        super().__init__(message)


# ---------------------------------------------------------------------------
# Range validation
# ---------------------------------------------------------------------------


def validate_int_range(
    value: Any,
    *,
    field: str,
    min: int,
    max: int,
) -> int:
    """Validate that *value* is an integer within [*min*, *max*].

    Mirrors the pattern established by ``_validate_cycle_minutes`` in
    ``src/blueprints/playlist.py`` but raises :class:`ValidationError`
    instead of returning an error response, so it can be used in pure
    validation code without Flask context.

    Args:
        value: The raw value to validate (will be coerced via ``int()``).
        field: Human-readable field name included in any error message.
        min: Inclusive lower bound.
        max: Inclusive upper bound.

    Returns:
        The validated integer value.

    Raises:
        ValidationError: If *value* cannot be converted to ``int`` or is
            outside [*min*, *max*].
    """
    try:
        int_val = int(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{field} must be an integer", field=field) from exc
    if int_val < min or int_val > max:
        raise ValidationError(
            f"{field} must be between {min} and {max}",
            field=field,
        )
    return int_val


# ---------------------------------------------------------------------------
# Schema-based validation
# ---------------------------------------------------------------------------

try:
    import jsonschema as _jsonschema
except ImportError:  # pragma: no cover
    _jsonschema = None


def validate_json_schema(data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Validate *data* against *schema* (JSON Schema draft 2020-12).

    Uses ``jsonschema`` when available; falls back to a no-op when the
    library is absent (library is listed in requirements, so this is a
    safety net only).

    Args:
        data: The dictionary to validate.
        schema: A JSON Schema dict.

    Returns:
        A list of human-readable error strings.  An empty list means
        validation passed.
    """
    if _jsonschema is None:  # pragma: no cover
        logger.debug("jsonschema not available; skipping schema validation")
        return []

    errors: list[str] = []
    try:
        validator = _jsonschema.Draft202012Validator(schema)
        for err in validator.iter_errors(data):
            try:
                path = ".".join(str(p) for p in err.path)
                msg = f"{path}: {err.message}" if path else err.message
            except Exception:
                msg = str(err)
            errors.append(msg)
    except Exception as exc:
        logger.debug("JSON schema validation encountered an error: %s", exc)
    return errors


# ---------------------------------------------------------------------------
# Required-field validation
# ---------------------------------------------------------------------------


class MissingFieldsError(ValueError):
    """Raised when one or more required form fields are absent or empty.

    Attributes:
        missing: List of human-readable field labels that failed validation.
        message: Pre-formatted error string.
    """

    def __init__(self, missing: list[str]) -> None:
        self.missing: list[str] = list(missing)
        self.message: str = f"Required fields missing: {', '.join(missing)}"
        super().__init__(self.message)


def validate_required(data: dict[str, Any], required: list[str]) -> None:
    """Raise :class:`MissingFieldsError` if any required key is absent or empty.

    A field is considered *missing* when its value in *data* is ``None``, an
    empty string, or a string consisting entirely of whitespace.

    Args:
        data: Mapping of field names to values (e.g. parsed form data).
        required: List of keys that must be present and non-empty.

    Raises:
        MissingFieldsError: If one or more required fields are missing.
    """

    def _is_empty(val: Any) -> bool:
        if val is None:
            return True
        return not str(val).strip()

    missing = [key for key in required if key not in data or _is_empty(data[key])]
    if missing:
        raise MissingFieldsError(missing)


# ---------------------------------------------------------------------------
# Plugin schema validation
# ---------------------------------------------------------------------------


def validate_plugin_required_fields(
    plugin: Any, form_data: dict[str, Any]
) -> str | None:
    """Validate required fields from a plugin schema against form data.

    Walks the ``sections`` / ``items`` tree returned by
    ``plugin.build_settings_schema()`` and checks that every field with
    ``required=True`` has a non-empty value in *form_data*.

    This is a pure extraction of the inline ``_validate_required_fields``
    helper that previously lived in ``src/blueprints/plugin.py``.

    Args:
        plugin: A plugin instance that may expose ``build_settings_schema()``.
        form_data: The parsed form values to validate against.

    Returns:
        An error message string if validation fails, or ``None`` on success.
    """
    if not hasattr(plugin, "build_settings_schema"):
        return None
    try:
        schema = plugin.build_settings_schema()
    except Exception:
        return None

    missing: list[str] = []

    def _check_items(items: list[dict[str, Any]]) -> None:
        for item in items:
            kind = item.get("kind", "")
            if kind == "row":
                _check_items(item.get("items", []))
            elif kind == "field":
                name = item.get("name", "")
                if item.get("required") and not str(form_data.get(name, "")).strip():
                    missing.append(item.get("label", name))

    for section in schema.get("sections", []):
        _check_items(section.get("items", []))

    if missing:
        return f"Required fields missing: {', '.join(missing)}"
    return None


# ---------------------------------------------------------------------------
# FormRequest dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormRequest:
    """Immutable wrapper around parsed and validated form input.

    Attributes:
        data: The raw parsed form data dictionary.
        plugin_id: Extracted ``plugin_id`` value (may be empty string if absent).
        extra: Any additional metadata attached at construction time.
    """

    data: dict[str, Any] = field(default_factory=dict)
    plugin_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FormRequest:
        """Construct a :class:`FormRequest` from a raw form data dict.

        Extracts ``plugin_id`` from the dict (without mutating it) and stores
        the original dict as :attr:`data`.

        Args:
            raw: Parsed form data, e.g. from ``parse_form(request.form)``.

        Returns:
            A populated :class:`FormRequest`.
        """
        plugin_id = str(raw.get("plugin_id") or "")
        return cls(data=dict(raw), plugin_id=plugin_id)

import logging
import os
import re
import tempfile
from typing import Any

from dotenv import dotenv_values
from flask import Blueprint, Response, render_template, request

from utils.http_utils import json_error, json_internal_error, json_success
from utils.request_models import parse_api_keys_save_request

logger = logging.getLogger(__name__)
apikeys_bp = Blueprint("apikeys", __name__)

# Sonar S1192 — readable alternatives to chr() escape sequences
_BACKSLASH = "\\"
_DOUBLE_QUOTE = '"'

# Internal app secrets that must never appear in the user-facing API Keys UI (JTN-309).
# These are application-level secrets, not provider API credentials.
_INTERNAL_KEYS: frozenset[str] = frozenset(
    {
        "SECRET_KEY",
        "TEST_KEY",
        "WTF_CSRF_SECRET_KEY",
    }
)

API_KEY_VALIDATION_ERROR = "Invalid API key entry"


# Path to .env file
def get_env_path() -> str:
    """Get path to .env file in the project root."""
    project_dir = os.environ.get("PROJECT_DIR")
    if project_dir:
        return os.path.join(project_dir, ".env")
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base_dir, ".env")


def parse_env_file(filepath: str) -> list[tuple[str, str]]:
    """Parse .env file and return list of (key, value) tuples."""
    if not os.path.exists(filepath):
        return []

    try:
        env_dict = dotenv_values(filepath)
        return list(env_dict.items())
    except Exception as e:
        logger.error(f"Error parsing .env file: {e}")
        return []


def _has_invalid_control_chars(value: str) -> bool:
    """Return True if *value* contains control characters that are not safe in .env files."""
    return any(
        (ord(ch) < 32 and ch not in ("\t",)) or ch in ("\n", "\r") for ch in value
    )


def _validate_api_key_entry(
    entry: object, existing_values: dict[str, str]
) -> tuple[str | None, str, Response | dict[str, Any] | tuple[Any, int] | None]:
    """Validate a single API key entry dict and resolve its value.

    Returns ``(key, value, None)`` on success, or ``(None, None, error_response)``
    when validation fails.  Empty keys are returned as ``("", "", None)`` to signal
    "skip this entry" without an error.
    """
    if not isinstance(entry, dict):
        return None, "", json_error("Each entry must be an object", status=400)

    raw_key = entry.get("key", "")
    if not isinstance(raw_key, str):
        return None, "", json_error("Entry key must be a string", status=400)
    key = raw_key.strip()

    keep_existing = entry.get("keepExisting", False)
    if not isinstance(keep_existing, bool):
        return (
            None,
            "",
            json_error("keepExisting must be a boolean", status=400),
        )

    if not key:
        return "", "", None

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return None, "", json_error("Invalid key format", status=400)

    if keep_existing:
        value = existing_values.get(key) or ""
    else:
        raw_value = entry.get("value", "")
        if not isinstance(raw_value, str):
            return (
                None,
                "",
                json_error("Entry value must be a string", status=400),
            )
        value = raw_value.strip()

    if _has_invalid_control_chars(value):
        return (
            None,
            "",
            json_error("Invalid characters in value", status=400),
        )

    return key, value, None


def write_env_file(filepath: str, entries: list[tuple[str, str]]) -> bool:
    """Write entries to .env file atomically via tempfile + os.replace."""
    try:
        env_dir = os.path.dirname(filepath) or "."
        fd, tmp_path = tempfile.mkstemp(dir=env_dir, prefix=".env.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("# InkyPi API Keys and Secrets\n")
                f.write("# Managed via web interface\n\n")
                for key, value in entries:
                    if _has_invalid_control_chars(value):
                        raise ValueError(
                            f"Invalid control character in value for key: {key}"
                        )
                    # Quote values with spaces or special characters
                    if " " in value or _DOUBLE_QUOTE in value or "'" in value:
                        value = f'"{value.replace(_BACKSLASH, _BACKSLASH * 2).replace(_DOUBLE_QUOTE, _BACKSLASH + _DOUBLE_QUOTE)}"'
                    f.write(f"{key}={value}\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, filepath)
        finally:
            # Clean up temp file if os.replace didn't run
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
        return True
    except Exception as e:
        logger.error(f"Error writing .env file: {e}")
        return False


def mask_value(value: str) -> str:
    """Mask API key value for display.

    Reveals only the final four characters so operators can tell which key
    they stored without exposing the token itself (matches the prototype's
    `sk-****-4d2f` style while staying conservative on what's leaked).
    """
    if not value:
        return "(empty)"
    if len(value) <= 4:
        return "●" * len(value)
    return "●" * 8 + value[-4:]


@apikeys_bp.route("/api-keys", methods=["GET"])  # type: ignore
def apikeys_page() -> Response | str:
    """Render API keys management page."""
    env_path = get_env_path()
    entries = parse_env_file(env_path)

    # Prepare entries for template: only key and masked value (no real values for security).
    # Skip internal app secrets so they are never exposed in the UI (JTN-309).
    template_entries = [
        {"key": key, "masked": mask_value(value)}
        for key, value in entries
        if key not in _INTERNAL_KEYS
    ]

    api_key_plugins = {
        "OPEN_AI_SECRET": ["AI Image", "AI Text"],
        "GOOGLE_AI_SECRET": ["AI Image", "AI Text"],
        "OPEN_WEATHER_MAP_SECRET": ["Weather"],
        "NASA_SECRET": ["NASA APOD"],
        "UNSPLASH_ACCESS_KEY": ["Unsplash Background"],
        "GITHUB_SECRET": ["GitHub"],
    }
    return render_template(
        "api_keys.html",
        entries=template_entries,
        env_exists=os.path.exists(env_path),
        api_keys_mode="generic",
        masked={},
        api_key_plugins=api_key_plugins,
        active_nav="api-keys",
    )


@apikeys_bp.route("/api-keys/save", methods=["POST"])  # type: ignore
def save_apikeys() -> tuple[Response | dict[str, Any], int] | Response | dict[str, Any]:
    """Save API keys to .env file."""
    try:
        parsed, parse_error = parse_api_keys_save_request(request.get_json(silent=True))
        if parse_error is not None:
            return json_error(parse_error.message, status=parse_error.status)
        if parsed is None:
            return json_error("Invalid JSON payload", status=400)

        # Load existing values for keys marked as keepExisting
        env_path = get_env_path()
        existing_values = dict(parse_env_file(env_path))

        # Validate and process entries
        valid_entries: list[tuple[str, str]] = []
        for entry in parsed.entries:
            key, value, err = _validate_api_key_entry(entry, existing_values)
            if err is not None:
                return json_error(API_KEY_VALIDATION_ERROR, status=400)
            if not key:
                continue
            valid_entries.append((key, value))

        if write_env_file(env_path, valid_entries):
            # Keys are persisted in .env; plugins reload via
            # device_config.load_env_key() which calls load_dotenv().
            # Do NOT inject into os.environ to avoid leaking secrets
            # in process memory (/proc/<pid>/environ).
            return json_success(
                f"Saved {len(valid_entries)} API key(s). Some plugins may require restart to pick up changes."
            )
        return json_error("Failed to write .env file", status=500)

    except Exception as e:
        logger.error(f"Error saving API keys: {e}")
        return json_internal_error("save API keys")

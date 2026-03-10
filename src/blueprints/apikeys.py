import logging
import os
import re
import tempfile

from dotenv import dotenv_values
from flask import Blueprint, render_template, request

from utils.http_utils import json_error, json_internal_error, json_success

logger = logging.getLogger(__name__)
apikeys_bp = Blueprint("apikeys", __name__)

# Path to .env file
def get_env_path():
    """Get path to .env file in the project root."""
    project_dir = os.environ.get("PROJECT_DIR")
    if project_dir:
        return os.path.join(project_dir, ".env")
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base_dir, '.env')


def parse_env_file(filepath):
    """Parse .env file and return list of (key, value) tuples."""
    if not os.path.exists(filepath):
        return []
    
    try:
        env_dict = dotenv_values(filepath)
        return list(env_dict.items())
    except Exception as e:
        logger.error(f"Error parsing .env file: {e}")
        return []


def write_env_file(filepath, entries):
    """Write entries to .env file atomically via tempfile + os.replace."""
    try:
        env_dir = os.path.dirname(filepath) or "."
        fd, tmp_path = tempfile.mkstemp(dir=env_dir, prefix=".env.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("# InkyPi API Keys and Secrets\n")
                f.write("# Managed via web interface\n\n")
                for key, value in entries:
                    if any((ord(ch) < 32 and ch not in ("\t",)) or ch in ("\n", "\r") for ch in value):
                        raise ValueError(f"Invalid control character in value for key: {key}")
                    # Quote values with spaces or special characters
                    if ' ' in value or '"' in value or "'" in value:
                        value = f'"{value}"'
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


def mask_value(value):
    """Mask API key value for display. Never reveal actual values for security."""
    if not value:
        return "(empty)"
    return "●" * min(len(value), 20)


@apikeys_bp.route('/api-keys')
def apikeys_page():
    """Render API keys management page."""
    env_path = get_env_path()
    entries = parse_env_file(env_path)
    
    # Prepare entries for template: only key and masked value (no real values for security)
    template_entries = [
        {"key": key, "masked": mask_value(value)}
        for key, value in entries
    ]
    
    api_key_plugins = {
        "OPEN_AI_SECRET": ["AI Image", "AI Text"],
        "OPEN_WEATHER_MAP_SECRET": ["Weather"],
        "NASA_SECRET": ["NASA APOD"],
        "UNSPLASH_ACCESS_KEY": ["Unsplash Background"],
        "GITHUB_SECRET": ["GitHub"],
    }
    return render_template(
        'api_keys.html',
        entries=template_entries,
        env_exists=os.path.exists(env_path),
        api_keys_mode="generic",
        masked={},
        api_key_plugins=api_key_plugins,
    )


@apikeys_bp.route('/api-keys/save', methods=['POST'])
def save_apikeys():
    """Save API keys to .env file."""
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return json_error("Invalid JSON payload", status=400)
        entries = data.get('entries', [])
        if not isinstance(entries, list):
            return json_error("Invalid entries format", status=400)

        # Load existing values for keys marked as keepExisting
        env_path = get_env_path()
        existing_values = dict(parse_env_file(env_path))

        # Validate and process entries
        valid_entries = []
        for entry in entries:
            key = entry.get('key', '').strip()
            keep_existing = entry.get('keepExisting', False)

            if not key:
                continue

            # Validate key format
            if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
                return json_error(f"Invalid key format: {key}", status=400)

            if keep_existing:
                # Use existing value from .env file
                value = existing_values.get(key, '')
            else:
                # Use provided value
                value = entry.get('value', '').strip()
            if any((ord(ch) < 32 and ch not in ("\t",)) or ch in ("\n", "\r") for ch in value):
                return json_error(f"Invalid characters in value for key: {key}", status=400)

            valid_entries.append((key, value))

        if write_env_file(env_path, valid_entries):
            # Reload environment variables
            for key, value in valid_entries:
                os.environ[key] = value

            return json_success(
                f"Saved {len(valid_entries)} API key(s). Some plugins may require restart to pick up changes."
            )
        else:
            return json_error("Failed to write .env file", status=500)

    except Exception as e:
        logger.error(f"Error saving API keys: {e}")
        return json_internal_error("save API keys")

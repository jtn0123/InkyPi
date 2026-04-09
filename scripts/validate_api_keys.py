#!/usr/bin/env python3
"""validate_api_keys.py — probe configured plugin API keys and report status.

Usage:
    python scripts/validate_api_keys.py [--config PATH] [--env PATH]
                                        [--plugin PLUGIN_ID] [--timeout N]
                                        [--json]

Exit codes:
    0  all probed keys are OK (or nothing to probe)
    1  at least one key is Invalid
    2  at least one key produced a network / unexpected error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------
STATUS_OK = "OK"
STATUS_INVALID = "Invalid"
STATUS_QUOTA = "Quota"
STATUS_NETWORK_ERROR = "NetworkError"
STATUS_UNKNOWN = "Unknown"
STATUS_SKIPPED = "Skipped"


# ---------------------------------------------------------------------------
# Per-plugin probe definitions
# Each entry: env_key -> (probe_fn, plugin_ids_that_use_this_key)
# ---------------------------------------------------------------------------


def _probe_openweathermap(key: str, timeout: int) -> tuple[str, str]:
    """Minimal geocoding call — returns a list, no side-effects."""
    import requests

    url = "https://api.openweathermap.org/geo/1.0/reverse"
    params = {"lat": "51.5074", "lon": "-0.1278", "limit": "1", "appid": key}
    try:
        r = requests.get(url, params=params, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    except requests.exceptions.Timeout:
        return STATUS_NETWORK_ERROR, "Request timed out"
    except requests.exceptions.RequestException as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    if r.status_code == 200:
        return STATUS_OK, "Geocoding responded 200"
    if r.status_code in (401, 403):
        return STATUS_INVALID, f"HTTP {r.status_code}"
    if r.status_code == 429:
        return STATUS_QUOTA, "Rate limit exceeded"
    return STATUS_UNKNOWN, f"HTTP {r.status_code}"


def _probe_openai(key: str, timeout: int) -> tuple[str, str]:
    """List available models — read-only, no cost."""
    import requests

    url = "https://api.openai.com/v1/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    except requests.exceptions.Timeout:
        return STATUS_NETWORK_ERROR, "Request timed out"
    except requests.exceptions.RequestException as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    if r.status_code == 200:
        return STATUS_OK, "Models endpoint responded 200"
    if r.status_code in (401, 403):
        return STATUS_INVALID, f"HTTP {r.status_code}"
    if r.status_code == 429:
        return STATUS_QUOTA, "Rate limit exceeded"
    return STATUS_UNKNOWN, f"HTTP {r.status_code}"


def _probe_google_ai(key: str, timeout: int) -> tuple[str, str]:
    """List Gemini models — read-only, no cost."""
    import requests

    url = "https://generativelanguage.googleapis.com/v1beta/models"
    params = {"key": key}
    try:
        r = requests.get(url, params=params, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    except requests.exceptions.Timeout:
        return STATUS_NETWORK_ERROR, "Request timed out"
    except requests.exceptions.RequestException as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    if r.status_code == 200:
        return STATUS_OK, "Models endpoint responded 200"
    if r.status_code in (400, 401, 403):
        return STATUS_INVALID, f"HTTP {r.status_code}"
    if r.status_code == 429:
        return STATUS_QUOTA, "Rate limit exceeded"
    return STATUS_UNKNOWN, f"HTTP {r.status_code}"


def _probe_unsplash(key: str, timeout: int) -> tuple[str, str]:
    """Fetch a single random photo — read-only."""
    import requests

    url = "https://api.unsplash.com/photos/random"
    params = {"client_id": key, "count": "1"}
    try:
        r = requests.get(url, params=params, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    except requests.exceptions.Timeout:
        return STATUS_NETWORK_ERROR, "Request timed out"
    except requests.exceptions.RequestException as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    if r.status_code == 200:
        return STATUS_OK, "Random photo endpoint responded 200"
    if r.status_code in (401, 403):
        return STATUS_INVALID, f"HTTP {r.status_code}"
    if r.status_code == 429:
        return STATUS_QUOTA, "Rate limit exceeded"
    return STATUS_UNKNOWN, f"HTTP {r.status_code}"


def _probe_nasa(key: str, timeout: int) -> tuple[str, str]:
    """Fetch today's APOD metadata — read-only, free tier allows DEMO_KEY."""
    import requests

    url = "https://api.nasa.gov/planetary/apod"
    params = {"api_key": key, "thumbs": "true"}
    try:
        r = requests.get(url, params=params, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    except requests.exceptions.Timeout:
        return STATUS_NETWORK_ERROR, "Request timed out"
    except requests.exceptions.RequestException as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    if r.status_code == 200:
        return STATUS_OK, "APOD endpoint responded 200"
    if r.status_code in (400, 401, 403):
        return STATUS_INVALID, f"HTTP {r.status_code}"
    if r.status_code == 429:
        return STATUS_QUOTA, "Rate limit exceeded"
    return STATUS_UNKNOWN, f"HTTP {r.status_code}"


def _probe_github(key: str, timeout: int) -> tuple[str, str]:
    """Hit /user endpoint — read-only, returns authenticated user."""
    import requests

    url = "https://api.github.com/user"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    except requests.exceptions.Timeout:
        return STATUS_NETWORK_ERROR, "Request timed out"
    except requests.exceptions.RequestException as exc:
        return STATUS_NETWORK_ERROR, str(exc)
    if r.status_code == 200:
        return STATUS_OK, "GitHub /user responded 200"
    if r.status_code in (401, 403):
        return STATUS_INVALID, f"HTTP {r.status_code}"
    if r.status_code == 429:
        return STATUS_QUOTA, "Rate limit exceeded"
    return STATUS_UNKNOWN, f"HTTP {r.status_code}"


# ---------------------------------------------------------------------------
# Registry: env-var-name -> (probe_fn, human_service_name, [plugin_ids])
# ---------------------------------------------------------------------------

PROBES: dict[str, tuple[Any, str, list[str]]] = {
    "OPENWEATHER_API_KEY": (
        _probe_openweathermap,
        "OpenWeatherMap",
        ["weather"],
    ),
    "OPEN_AI_SECRET": (
        _probe_openai,
        "OpenAI",
        ["ai_image", "ai_text"],
    ),
    "GOOGLE_AI_SECRET": (
        _probe_google_ai,
        "Google AI",
        ["ai_image", "ai_text"],
    ),
    "UNSPLASH_ACCESS_KEY": (
        _probe_unsplash,
        "Unsplash",
        ["unsplash"],
    ),
    "NASA_SECRET": (
        _probe_nasa,
        "NASA APOD",
        ["apod"],
    ),
    "GITHUB_SECRET": (
        _probe_github,
        "GitHub",
        ["github"],
    ),
}


# ---------------------------------------------------------------------------
# Config / .env helpers (standalone — no src/ imports)
# ---------------------------------------------------------------------------


def _load_env_file(env_path: str) -> dict[str, str]:
    """Parse a .env file and return a dict of key -> value."""
    result: dict[str, str] = {}
    if not os.path.isfile(env_path):
        return result
    with open(env_path) as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                result[key] = value
    return result


def _find_env_path(config_path: str) -> str:
    """Derive the .env path from the config file location (mirror Config logic)."""
    project_dir = os.getenv("PROJECT_DIR")
    if project_dir:
        return os.path.join(project_dir, ".env")
    # config lives at <repo>/src/config/device*.json — go up two levels for repo root
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(config_path)))
    return os.path.join(os.path.dirname(src_dir), ".env")


def _load_device_config(config_path: str) -> dict[str, Any]:
    """Load device.json and return the parsed dict."""
    with open(config_path) as fh:
        return json.load(fh)


def _extract_configured_plugin_ids(device_config: dict[str, Any]) -> set[str]:
    """Walk playlist_config to find all plugin IDs that appear in playlists."""
    ids: set[str] = set()
    playlist_cfg = device_config.get("playlist_config", {})
    for playlist in playlist_cfg.get("playlists", []):
        for plugin_entry in playlist.get("plugins", []):
            pid = plugin_entry.get("plugin_id")
            if pid:
                ids.add(pid)
    return ids


# ---------------------------------------------------------------------------
# Core probe runner
# ---------------------------------------------------------------------------


def run_probes(
    env_keys: dict[str, str],
    configured_plugin_ids: set[str],
    plugin_filter: str | None,
    timeout: int,
) -> list[dict[str, str]]:
    """Return a list of result dicts for all relevant probes."""
    results: list[dict[str, str]] = []

    for env_key, (probe_fn, service_name, plugin_ids) in PROBES.items():
        # Apply --plugin filter
        if plugin_filter and plugin_filter not in plugin_ids:
            continue

        key_value = env_keys.get(env_key, "")

        if not key_value:
            # Key not set — only report if the plugin is configured
            if any(pid in configured_plugin_ids for pid in plugin_ids):
                results.extend(
                    {
                        "plugin": pid,
                        "service": service_name,
                        "env_key": env_key,
                        "status": STATUS_SKIPPED,
                        "message": "Key not set in .env",
                    }
                    for pid in plugin_ids
                    if pid in configured_plugin_ids
                )
            elif plugin_filter:
                results.append(
                    {
                        "plugin": plugin_filter,
                        "service": service_name,
                        "env_key": env_key,
                        "status": STATUS_SKIPPED,
                        "message": "Key not set in .env",
                    }
                )
            continue

        # Run the probe once per key
        status, message = probe_fn(key_value, timeout)

        # Emit one row per relevant plugin
        for pid in plugin_ids:
            if plugin_filter and pid != plugin_filter:
                continue
            if not plugin_filter and pid not in configured_plugin_ids:
                # Key is present but plugin not configured — still probe & report
                pass
            results.append(
                {
                    "plugin": pid,
                    "service": service_name,
                    "env_key": env_key,
                    "status": status,
                    "message": message,
                }
            )

    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_STATUS_EMOJI = {
    STATUS_OK: "OK      ",
    STATUS_INVALID: "INVALID ",
    STATUS_QUOTA: "QUOTA   ",
    STATUS_NETWORK_ERROR: "NETERR  ",
    STATUS_UNKNOWN: "UNKNOWN ",
    STATUS_SKIPPED: "skipped ",
}


def _print_table(results: list[dict[str, str]]) -> None:
    if not results:
        print("No plugins with API keys found in configuration.")
        return
    col_plugin = max(len(r["plugin"]) for r in results)
    col_service = max(len(r["service"]) for r in results)
    header = (
        f"{'Plugin':<{col_plugin}}  {'Service':<{col_service}}  "
        f"{'Status':<8}  Message"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        tag = _STATUS_EMOJI.get(r["status"], r["status"][:8].ljust(8))
        print(
            f"{r['plugin']:<{col_plugin}}  {r['service']:<{col_service}}  "
            f"{tag}  {r['message']}"
        )


def _exit_code(results: list[dict[str, str]]) -> int:
    statuses = {r["status"] for r in results}
    if STATUS_INVALID in statuses:
        return 1
    if {STATUS_NETWORK_ERROR, STATUS_UNKNOWN} & statuses:
        return 2
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate InkyPi plugin API keys by probing their endpoints."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to device.json (default: src/config/device.json relative to repo root)",
    )
    parser.add_argument(
        "--env",
        default=None,
        help="Path to .env file (default: derived from --config location)",
    )
    parser.add_argument(
        "--plugin",
        default=None,
        help="Limit validation to a single plugin ID (e.g. weather)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args(argv)

    # Resolve config path
    config_path = args.config
    if config_path is None:
        # Try to find it relative to this script's location (scripts/ -> repo root)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(script_dir)
        candidates = [
            os.path.join(repo_root, "src", "config", "device.json"),
            os.path.join(repo_root, "src", "config", "device_dev.json"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                config_path = candidate
                break
        if config_path is None:
            print(
                "ERROR: Could not find device.json. Use --config to specify path.",
                file=sys.stderr,
            )
            return 2

    if not os.path.isfile(config_path):
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        return 2

    # Resolve .env path
    env_path = args.env or _find_env_path(config_path)

    # Load data
    try:
        device_config = _load_device_config(config_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: Failed to read config: {exc}", file=sys.stderr)
        return 2

    env_keys = _load_env_file(env_path)
    configured_plugin_ids = _extract_configured_plugin_ids(device_config)

    results = run_probes(env_keys, configured_plugin_ids, args.plugin, args.timeout)

    if args.output_json:
        print(json.dumps(results, indent=2))
    else:
        _print_table(results)

    return _exit_code(results)


if __name__ == "__main__":
    sys.exit(main())

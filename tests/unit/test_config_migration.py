"""Regression tests for legacy device.json schema migration compatibility (JTN-736)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

import config as config_mod

LEGACY_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "legacy_configs"
)
LEGACY_FIXTURE_VERSIONS = ("v0.40", "v0.45", "v0.50", "v0.53", "current")

# User-facing values that must never silently disappear during loader migrations.
SENTINEL_PATHS = (
    "name",
    "timezone",
    "time_format",
    "playlist_config.playlists.0.name",
    "playlist_config.playlists.0.plugins.0.plugin_id",
    "playlist_config.playlists.0.plugins.0.name",
    "playlist_config.playlists.0.plugins.0.plugin_settings.api_token",
    "playlist_config.playlists.0.plugins.0.plugin_settings.custom_banner",
)


def _fixture_device_path(fixture_name: str) -> Path:
    return LEGACY_FIXTURE_ROOT / fixture_name / "device.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _path_get(payload: object, dotted_path: str) -> object:
    node: object = payload
    for segment in dotted_path.split("."):
        if isinstance(node, list):
            node = node[int(segment)]
            continue
        if not isinstance(node, dict):
            raise KeyError(f"{dotted_path}: expected mapping at '{segment}'")
        node = node[segment]
    return node


def _assert_paths_preserved(
    expected_payload: dict,
    actual_payload: dict,
    paths: tuple[str, ...],
) -> None:
    for dotted_path in paths:
        expected_value = _path_get(expected_payload, dotted_path)
        actual_value = _path_get(actual_payload, dotted_path)
        assert expected_value == actual_value, (
            f"Path '{dotted_path}' changed during migration: "
            f"expected={expected_value!r} actual={actual_value!r}"
        )


def _expected_cycle_interval_seconds(playlist_dict: dict) -> int | None:
    cycle_seconds = playlist_dict.get("cycle_interval_seconds")
    if isinstance(cycle_seconds, int) and cycle_seconds > 0:
        return cycle_seconds

    cycle_minutes = playlist_dict.get("cycle_minutes")
    if isinstance(cycle_minutes, int) and cycle_minutes > 0:
        return cycle_minutes * 60
    return None


@pytest.mark.parametrize("fixture_name", LEGACY_FIXTURE_VERSIONS)
def test_legacy_configs_load_and_preserve_sentinel_fields(
    fixture_name: str,
    monkeypatch,
    tmp_path,
):
    # Lazy import keeps the production `utils.config_schema` dependency
    # contained inside the test body (Sonar pythonarchitecture:S7788).
    from utils.config_schema import validate_device_config

    fixture_path = _fixture_device_path(fixture_name)
    raw_fixture = _load_json(fixture_path)

    config_path = tmp_path / "device.json"
    shutil.copyfile(fixture_path, config_path)
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))

    cfg = config_mod.Config()
    loaded = cfg.get_config()

    # (a) no crash + (d) resulting config shape remains valid.
    validate_device_config(loaded)

    # (b) no silent key drops for critical user-facing values.
    _assert_paths_preserved(raw_fixture, loaded, SENTINEL_PATHS)

    # (c) migration behavior: legacy cycle_minutes/schedule aliases map correctly.
    playlist = cfg.get_playlist_manager().get_playlist("Default")
    assert playlist is not None
    expected_cycle_seconds = _expected_cycle_interval_seconds(
        raw_fixture["playlist_config"]["playlists"][0]
    )
    assert playlist.cycle_interval_seconds == expected_cycle_seconds

    plugin = playlist.plugins[0]
    legacy_schedule = (
        raw_fixture["playlist_config"]["playlists"][0]["plugins"][0]
        .get("refresh", {})
        .get("schedule")
    )
    if legacy_schedule is not None:
        assert plugin.refresh.get("scheduled") == legacy_schedule


def test_corrupt_but_recoverable_fixture_uses_safe_refresh_defaults(
    monkeypatch,
    tmp_path,
):
    fixture_path = _fixture_device_path("corrupt_recoverable")
    config_path = tmp_path / "device.json"
    shutil.copyfile(fixture_path, config_path)
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))

    cfg = config_mod.Config()
    refresh_info = cfg.get_refresh_info()
    assert refresh_info.refresh_type == "Manual Update"
    assert refresh_info.plugin_id == ""
    assert refresh_info.refresh_time is None


def test_renamed_key_without_migration_is_detected(
    monkeypatch,
    tmp_path,
):
    baseline = _load_json(_fixture_device_path("v0.40"))
    renamed = copy.deepcopy(baseline)
    renamed["tz_name"] = renamed.pop("timezone")

    config_path = tmp_path / "device.json"
    config_path.write_text(json.dumps(renamed), encoding="utf-8")
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))

    cfg = config_mod.Config()

    with pytest.raises((AssertionError, KeyError), match="timezone"):
        _assert_paths_preserved(baseline, cfg.get_config(), ("timezone",))

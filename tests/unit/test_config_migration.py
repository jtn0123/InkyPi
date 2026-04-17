"""Regression tests for legacy device.json schema migration compatibility (JTN-736)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from tests.helpers.config_runtime_helpers import assert_valid_device_config
from tests.helpers.path_utils import assert_baseline_preserved, path_get

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


def _coerce_positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            coerced = int(stripped)
        except ValueError:
            return None
        if coerced > 0:
            return coerced
    return None


def _expected_cycle_interval_seconds(playlist_dict: dict) -> int | None:
    cycle_seconds = _coerce_positive_int(playlist_dict.get("cycle_interval_seconds"))
    if cycle_seconds is not None:
        return cycle_seconds

    cycle_minutes = _coerce_positive_int(playlist_dict.get("cycle_minutes"))
    if cycle_minutes is not None:
        return cycle_minutes * 60
    return None


@pytest.mark.parametrize("fixture_name", LEGACY_FIXTURE_VERSIONS)
def test_legacy_configs_load_and_preserve_sentinel_fields(
    fixture_name: str,
    monkeypatch,
    tmp_path,
):
    fixture_path = _fixture_device_path(fixture_name)
    raw_fixture = _load_json(fixture_path)

    config_path = tmp_path / "device.json"
    shutil.copyfile(fixture_path, config_path)
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))

    cfg = config_mod.Config()
    loaded = cfg.get_config()

    # (a) no crash + (d) resulting config shape remains valid.
    assert_valid_device_config(loaded)

    # (b) no silent key drops for critical user-facing values.
    baseline_values = {
        dotted_path: path_get(raw_fixture, dotted_path)
        for dotted_path in SENTINEL_PATHS
    }
    assert_baseline_preserved(
        baseline_values,
        loaded,
        SENTINEL_PATHS,
        version=fixture_name,
    )

    # (c) migration behavior: legacy cycle_minutes/schedule aliases map correctly.
    playlist_dicts = raw_fixture.get("playlist_config", {}).get("playlists", [])
    assert playlist_dicts, (
        f"{fixture_name} fixture must include a playlist to verify cycle/schedule migration"
    )
    plugin_dicts = playlist_dicts[0].get("plugins", [])
    assert plugin_dicts, (
        f"{fixture_name} fixture must include a plugin to verify schedule migration"
    )

    playlist = cfg.get_playlist_manager().get_playlist("Default")
    assert playlist is not None
    expected_cycle_seconds = _expected_cycle_interval_seconds(playlist_dicts[0])
    assert playlist.cycle_interval_seconds == expected_cycle_seconds

    plugin = playlist.plugins[0]
    legacy_schedule = plugin_dicts[0].get("refresh", {}).get("schedule")
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
        baseline_values = {"timezone": path_get(baseline, "timezone")}
        assert_baseline_preserved(
            baseline_values, cfg.get_config(), ("timezone",), version="renamed-key"
        )

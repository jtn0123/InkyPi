"""Playlist times follow one rule: the device config schema's.

The schema once only asked for two digits each side of the colon, so a
restored ``25:00`` was saved; three separate parsers then disagreed about it,
and the one the refresh loop used raised while choosing the active playlist,
so no playlist was ever chosen again. Now the schema says which times exist,
``utils.time_utils.parse_hhmm`` is the only reader, and device.json loads with
a bad playlist set aside instead of stopping the screen.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from model import Playlist
from refresh_task import schedule
from utils import config_schema
from utils.request_models import validate_playlist_times
from utils.time_utils import format_hhmm, parse_hhmm

REPO_ROOT = Path(__file__).resolve().parents[2]
TIME_RULE = ("playlist_config", "playlists", "start_time")
BAD_TIMES = ["24:01", "24:30", "25:00", "12:60", "99:99", "8:5", "08:00:00", "noon"]


def _schema_allows(value: str) -> bool:
    return jsonschema.Draft202012Validator(
        dict(config_schema.field_rules(*TIME_RULE))
    ).is_valid(value)


def _without_description(rules: Any) -> dict[str, Any]:
    return {key: value for key, value in rules.items() if key != "description"}


def test_the_schema_rule_reaches_list_items() -> None:
    end = config_schema.field_rules("playlist_config", "playlists", "end_time")
    start = config_schema.field_rules(*TIME_RULE)

    assert "pattern" in start
    assert _without_description(end) == _without_description(start)
    with pytest.raises(KeyError):
        config_schema.field_rules("playlist_config", "playlists", "colour")


def test_parse_hhmm_reads_exactly_the_times_the_schema_allows() -> None:
    for hours in range(100):
        for minutes in range(100):
            text = f"{hours:02d}:{minutes:02d}"
            allowed = _schema_allows(text)
            try:
                parsed: int | None = parse_hhmm(text)
            except ValueError:
                parsed = None
            assert (parsed is not None) == allowed, text
            if allowed:
                assert parsed == hours * 60 + minutes
                assert format_hhmm(hours * 60 + minutes) == text


def test_midnight_at_the_end_of_the_day_is_1440() -> None:
    assert parse_hhmm("24:00") == 1440
    assert format_hhmm(1440) == "24:00"


def test_a_typed_one_digit_hour_is_read_and_stored_with_two() -> None:
    assert parse_hhmm("8:05") == 485
    assert format_hhmm(parse_hhmm("8:05")) == "08:05"
    assert not _schema_allows("8:05")


@pytest.mark.parametrize("value", [" 08:00", "08:00\n", "٠٨:٠٠", "+8:00", None, 800])
def test_anything_but_digits_and_a_colon_is_refused(value: object) -> None:
    with pytest.raises(ValueError):
        parse_hhmm(value)


@pytest.mark.parametrize("bad", BAD_TIMES)
def test_every_reader_refuses_the_same_times(bad: str) -> None:
    *_, error = validate_playlist_times(bad, "10:00")
    assert error is not None and error.field == "start_time"

    assert schedule._minutes(bad) is None

    with pytest.raises(ValueError):
        Playlist("Bad", bad, "10:00").get_time_range_minutes()

    assert config_schema.playlist_problems(
        {"name": "Bad", "start_time": bad, "end_time": "10:00", "plugins": []}
    ) == [f"start time {bad!r} is not a time from 00:00 to 24:00"]


# --- device.json with a bad playlist ---------------------------------------


def _playlist(name: str, start: str, end: str) -> dict[str, Any]:
    return {
        "name": name,
        "start_time": start,
        "end_time": end,
        "plugins": [
            {
                "plugin_id": "clock",
                "name": f"{name} clock",
                "plugin_settings": {"face": "digital"},
                "refresh": {"interval": 300},
            }
        ],
    }


def _write_playlists(device_config: Any, playlists: list[dict[str, Any]]) -> Path:
    path = Path(device_config.config_file)
    data = json.loads(path.read_text())
    data["playlist_config"] = {"playlists": playlists, "active_playlist": None}
    path.write_text(json.dumps(data))
    return path


def test_load_sets_a_bad_playlist_aside_and_keeps_the_rest(
    device_config_dev: Any, caplog: pytest.LogCaptureFixture
) -> None:
    _write_playlists(
        device_config_dev,
        [_playlist("Evening", "25:00", "23:00"), _playlist("Day", "06:00", "22:00")],
    )

    with caplog.at_level(logging.ERROR):
        restarted = type(device_config_dev)()

    manager = restarted.get_playlist_manager()
    assert manager.get_playlist_names() == ["Day"]
    assert "playlist 'Evening' in device.json breaks the playlist rules" in caplog.text
    assert "start time '25:00' is not a time from 00:00 to 24:00" in caplog.text


def test_the_refresh_loop_still_picks_a_playlist_after_a_bad_one_loads(
    device_config_dev: Any,
) -> None:
    _write_playlists(
        device_config_dev,
        [_playlist("Evening", "25:00", "23:00"), _playlist("Day", "06:00", "22:00")],
    )
    manager = type(device_config_dev)().get_playlist_manager()
    noon = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)

    active = manager.determine_active_playlist(noon)

    assert active is not None and active.name == "Day"
    assert schedule.is_due(
        playlist_manager=manager,
        latest_refresh=None,
        last_attempt=None,
        now=noon,
        device_interval=300,
    )


def test_a_set_aside_playlist_is_kept_on_disk_with_its_reason(
    device_config_dev: Any, caplog: pytest.LogCaptureFixture
) -> None:
    evening = _playlist("Evening", "25:00", "23:00")
    path = _write_playlists(
        device_config_dev, [evening, _playlist("Day", "06:00", "22:00")]
    )
    restarted = type(device_config_dev)()

    restarted.write_config()
    on_disk = json.loads(path.read_text())

    assert [p["name"] for p in on_disk["playlist_config"]["playlists"]] == ["Day"]
    assert on_disk["skipped_playlists"] == [
        {
            "reason": "start time '25:00' is not a time from 00:00 to 24:00",
            "playlist": evening,
        }
    ]

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        again = type(device_config_dev)()

    assert again.get_config("skipped_playlists") == on_disk["skipped_playlists"]
    assert "keeps 1 playlist(s) set aside under skipped_playlists" in caplog.text
    assert "breaks the playlist rules" not in caplog.text


def test_only_the_playlists_section_is_forgiven_at_load(
    device_config_dev: Any,
) -> None:
    path = Path(device_config_dev.config_file)
    data = json.loads(path.read_text())
    data["orientation"] = "sideways"
    path.write_text(json.dumps(data))

    with pytest.raises(config_schema.ConfigValidationError):
        type(device_config_dev)()


def test_set_aside_leaves_a_shallow_copy_s_source_alone() -> None:
    playlists = [_playlist("Evening", "25:00", "23:00")]
    source = {"playlist_config": {"playlists": playlists, "active_playlist": None}}

    messages = config_schema.set_aside_invalid_playlists(dict(source))

    assert messages == [
        "Playlist 'Evening': start time '25:00' is not a time from 00:00 to 24:00"
    ]
    assert source["playlist_config"]["playlists"] == playlists


def _load_preflight() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_inkypi_preflight_rules", REPO_ROOT / "install" / "_preflight.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_update_gate_passes_a_config_the_app_would_load(tmp_path: Path) -> None:
    config = {
        "display_type": "mock",
        "playlist_config": {
            "playlists": [
                _playlist("Evening", "25:00", "23:00"),
                _playlist("Day", "06:00", "22:00"),
            ]
        },
    }
    path = tmp_path / "device.json"
    path.write_text(json.dumps(config))

    data = _load_preflight().load_and_validate_config(REPO_ROOT, path)

    # The gate checks a copy; what it returns is the file as read.
    assert len(data["playlist_config"]["playlists"]) == 2


def test_the_playlists_page_lists_set_aside_playlists(client: Any) -> None:
    device_config = client.application.config["DEVICE_CONFIG"]
    device_config.config["skipped_playlists"] = [
        {
            "reason": "start time '25:00' is not a time from 00:00 to 24:00",
            "playlist": _playlist("Evening <b>", "25:00", "23:00"),
        },
        {"reason": "", "playlist": {"start_time": "07:00"}},
        "not an entry",
    ]

    html = client.get("/playlist").get_data(as_text=True)

    assert 'id="setAsidePlaylistsBanner"' in html
    assert "2 playlists were set aside" in html
    assert (
        "<strong>Evening &lt;b&gt;</strong>: start time &#39;25:00&#39; is not a "
        "time from 00:00 to 24:00"
    ) in html
    assert "<strong>#2</strong>: it breaks the playlist rules" in html
    # Set aside means not shown as a playlist card.
    assert 'data-playlist-name="Evening' not in html


def test_the_playlists_page_has_no_banner_when_nothing_is_set_aside(
    client: Any,
) -> None:
    html = client.get("/playlist").get_data(as_text=True)

    assert "setAsidePlaylistsBanner" not in html

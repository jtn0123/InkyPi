import json
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient


def test_add_plugin_success_and_duplicate(client: FlaskClient) -> None:
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "My Clock",
                "refreshType": "interval",
                "unit": "minute",
                "interval": 10,
            }
        ),
    }
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True

    # Duplicate should be rejected
    resp2 = client.post("/add_plugin", data=payload)
    assert resp2.status_code == 400
    assert "already exists" in resp2.get_json().get("error", "")


def test_add_plugin_validation_errors(client: FlaskClient) -> None:
    bad_name = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "bad/name",  # slash not allowed
                "refreshType": "interval",
                "unit": "minute",
                "interval": 5,
            }
        ),
    }
    r1 = client.post("/add_plugin", data=bad_name)
    assert r1.status_code == 422
    assert "letters, numbers, spaces, underscores, and hyphens" in r1.get_json().get(
        "error", ""
    )

    missing_type = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "X",
                # missing refreshType
            }
        ),
    }
    r2 = client.post("/add_plugin", data=missing_type)
    assert r2.status_code == 422
    assert "Refresh type is required" in r2.get_json().get("error", "")


def _add_plugin_with_instance(client: FlaskClient, instance_name: Any) -> Any:
    """Helper: attempt to add a clock plugin with the given instance name."""
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": instance_name,
                "refreshType": "interval",
                "unit": "minute",
                "interval": 10,
            }
        ),
    }
    return client.post("/add_plugin", data=payload)


def test_instance_name_allows_underscore(client: FlaskClient) -> None:
    """JTN-471: underscore should be accepted in instance names."""
    resp = _add_plugin_with_instance(client, "weather_home")
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True


def test_instance_name_allows_hyphen(client: FlaskClient) -> None:
    """JTN-471: hyphen should be accepted in instance names."""
    resp = _add_plugin_with_instance(client, "my-plugin")
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True


def test_instance_name_allows_plain(client: FlaskClient) -> None:
    """JTN-471: plain alphanumeric name should be accepted."""
    resp = _add_plugin_with_instance(client, "plain")
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True


def test_instance_name_rejects_slash(client: FlaskClient) -> None:
    """JTN-471: slash must be rejected to prevent path traversal."""
    resp = _add_plugin_with_instance(client, "foo/bar")
    assert resp.status_code == 422
    assert "letters, numbers, spaces, underscores, and hyphens" in resp.get_json().get(
        "error", ""
    )


def test_instance_name_rejects_dotdot(client: FlaskClient) -> None:
    """JTN-471: ../etc traversal attempt must be rejected."""
    resp = _add_plugin_with_instance(client, "../etc")
    assert resp.status_code == 422
    assert "letters, numbers, spaces, underscores, and hyphens" in resp.get_json().get(
        "error", ""
    )


def test_instance_name_rejects_empty(client: FlaskClient) -> None:
    """JTN-471: empty instance name must be rejected."""
    resp = _add_plugin_with_instance(client, "")
    assert resp.status_code == 422
    assert "required" in resp.get_json().get("error", "").lower()


def test_create_playlist_error_paths(client: FlaskClient) -> None:
    # Equal times should be rejected
    resp = client.post(
        "/create_playlist",
        json={"playlist_name": "Bad", "start_time": "09:00", "end_time": "09:00"},
    )
    assert resp.status_code == 400

    # Missing JSON: Flask responds 415 (unsupported media type) without JSON
    resp2 = client.post("/create_playlist")
    assert resp2.status_code in (400, 415)

    # Duplicate name
    ok = client.post(
        "/create_playlist",
        json={"playlist_name": "Dupe", "start_time": "06:00", "end_time": "07:00"},
    )
    assert ok.status_code == 200
    dupe = client.post(
        "/create_playlist",
        json={"playlist_name": "Dupe", "start_time": "06:00", "end_time": "07:00"},
    )
    assert dupe.status_code == 400


def test_update_playlist_errors_and_failure_branch(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Missing required fields
    r = client.put("/update_playlist/Nope", json={})
    assert r.status_code == 400

    # Not found
    r2 = client.put(
        "/update_playlist/Nope",
        json={"new_name": "New", "start_time": "01:00", "end_time": "02:00"},
    )
    assert r2.status_code == 400

    # Create then force update to return False to hit 500 branch
    client.post(
        "/create_playlist",
        json={"playlist_name": "X", "start_time": "01:00", "end_time": "02:00"},
    )

    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    monkeypatch.setattr(pm, "update_playlist", lambda *args, **kwargs: False)

    r3 = client.put(
        "/update_playlist/X",
        json={"new_name": "Y", "start_time": "01:00", "end_time": "02:00"},
    )
    assert r3.status_code == 500


def test_delete_playlist_not_exist(client: FlaskClient) -> None:
    # JTN-782: missing playlist returns 404 (not_found) -> None -> None, not 400.
    resp = client.delete("/delete_playlist/NoSuch")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert data.get("code") == "not_found"


def test_eta_endpoint_and_request_ids(
    client: FlaskClient, device_config_dev: Any
) -> None:
    # Build a playlist with 2 plugins
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "A",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "B",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    device_config_dev.write_config()

    # ETA endpoint should return success and include request_id
    r = client.get("/playlist/eta/Default")
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("success") is True
    assert isinstance(j.get("request_id"), str) and len(j["request_id"]) > 0
    eta = j.get("eta") or {}
    # Should include the plugin keys
    assert "A" in eta and "B" in eta
    assert "minutes" in eta["A"] and "at" in eta["A"]

    # Not found case
    r2 = client.get("/playlist/eta/NoSuch")
    assert r2.status_code == 404
    j2 = r2.get_json()
    assert "error" in j2
    assert isinstance(j2.get("request_id"), str) and len(j2["request_id"]) > 0


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` is pinned, so calendar-day buckets are
    deterministic no matter what hour the suite runs at."""

    frozen: datetime

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return cls.frozen if tz is None else cls.frozen.astimezone(tz)


def _freeze_playlist_now(monkeypatch: pytest.MonkeyPatch, frozen: datetime) -> None:
    import blueprints.playlist._pages as playlist_mod

    _FrozenDatetime.frozen = frozen
    monkeypatch.setattr(playlist_mod, "datetime", _FrozenDatetime)


def test_format_relative_time_filter_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    from blueprints.playlist._pages import format_relative_time

    now = datetime(2026, 3, 10, 15, 0, tzinfo=UTC)
    _freeze_playlist_now(monkeypatch, now)

    # just now
    assert format_relative_time(now.isoformat()) == "just now"

    # minutes ago
    ten_min_ago = (now - timedelta(minutes=10)).isoformat()
    out = format_relative_time(ten_min_ago)
    assert "minutes ago" in out

    # today at
    earlier_today = (now - timedelta(hours=2)).isoformat()
    assert format_relative_time(earlier_today) == "today at 1:00 PM"

    # yesterday at
    yesterday = (now - timedelta(days=1, hours=1)).isoformat()
    assert format_relative_time(yesterday) == "yesterday at 2:00 PM"

    # older date formatted with month abbrev
    older = (now - timedelta(days=10)).isoformat()
    assert format_relative_time(older) == "Feb 28 at 3:00 PM"


def test_format_relative_time_buckets_by_calendar_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At 2 AM, a refresh at 8:55 PM the previous evening is "yesterday",
    not "today" (regression: rolling 24h window mislabelled it)."""
    from blueprints.playlist._pages import format_relative_time

    now = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)
    _freeze_playlist_now(monkeypatch, now)

    last_evening = datetime(2026, 3, 9, 20, 55, tzinfo=UTC).isoformat()
    assert format_relative_time(last_evening) == "yesterday at 8:55 PM"

    # 26h ago crosses two midnights -> dated label, not "yesterday".
    two_days = datetime(2026, 3, 8, 23, 59, tzinfo=UTC).isoformat()
    assert format_relative_time(two_days) == "Mar 8 at 11:59 PM"


def test_add_plugin_missing_playlist_name(client: FlaskClient) -> None:
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "instance_name": "My Clock",
                "refreshType": "interval",
                "unit": "minute",
                "interval": 10,
            }
        ),
    }
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 422
    assert "Playlist name is required" in resp.get_json().get("error", "")


def test_add_plugin_missing_instance_name(client: FlaskClient) -> None:
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "refreshType": "interval",
                "unit": "minute",
                "interval": 10,
            }
        ),
    }
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 422
    assert "Instance name is required" in resp.get_json().get("error", "")


def test_add_plugin_missing_refresh_unit(client: FlaskClient) -> None:
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "My Clock",
                "refreshType": "interval",
                "interval": 10,
            }
        ),
    }
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 422
    assert "Refresh interval unit is required" in resp.get_json().get("error", "")


def test_add_plugin_missing_refresh_interval(client: FlaskClient) -> None:
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "My Clock",
                "refreshType": "interval",
                "unit": "minute",
            }
        ),
    }
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 422
    assert "Refresh interval is required" in resp.get_json().get("error", "")


def test_add_plugin_missing_refresh_time_scheduled(client: FlaskClient) -> None:
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "My Clock",
                "refreshType": "scheduled",
            }
        ),
    }
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 422
    assert "Refresh time is required" in resp.get_json().get("error", "")


def test_add_plugin_playlist_manager_failure(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "My Clock",
                "refreshType": "interval",
                "unit": "minute",
                "interval": 10,
            }
        ),
    }

    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    monkeypatch.setattr(pm, "add_plugin_to_playlist", lambda *args, **kwargs: False)

    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 500
    assert "Failed to add to playlist" in resp.get_json().get("error", "")


def test_create_playlist_invalid_json(client: FlaskClient) -> None:
    resp = client.post("/create_playlist", data="not json")
    assert resp.status_code == 415  # Flask returns 415 for unsupported media type
    # The actual validation happens later, so we test that the endpoint handles it


def test_create_playlist_missing_name(client: FlaskClient) -> None:
    resp = client.post(
        "/create_playlist", json={"start_time": "06:00", "end_time": "09:00"}
    )
    assert resp.status_code == 400
    data = resp.get_json()
    # JTN-658: validator-owned messages are preserved end-to-end (they are
    # static strings so safe) and carry ``details.field`` for frontend
    # highlighting.
    assert "required" in data["error"].lower()
    assert data["details"]["field"] == "playlist_name"


def test_create_playlist_missing_times(client: FlaskClient) -> None:
    resp = client.post("/create_playlist", json={"playlist_name": "Test"})
    assert resp.status_code == 400
    assert "Start time and End time are required" in resp.get_json().get("error", "")


def test_create_playlist_playlist_manager_failure(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    monkeypatch.setattr(pm, "add_playlist", lambda *args, **kwargs: False)

    resp = client.post(
        "/create_playlist",
        json={"playlist_name": "Test", "start_time": "06:00", "end_time": "09:00"},
    )
    assert resp.status_code == 500
    assert "Failed to create playlist" in resp.get_json().get("error", "")


def test_create_playlist_exception_handling(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    monkeypatch.setattr(
        pm,
        "add_playlist",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("test")),
    )

    resp = client.post(
        "/create_playlist",
        json={"playlist_name": "Test", "start_time": "06:00", "end_time": "09:00"},
    )
    assert resp.status_code == 500
    body = resp.get_json()
    assert body.get("error") == "An internal error occurred"
    assert body.get("code") == "internal_error"
    assert body.get("details", {}).get("context") == "create playlist"


def test_update_playlist_rejects_equal_start_end(client: FlaskClient) -> None:
    # First create a playlist
    client.post(
        "/create_playlist",
        json={"playlist_name": "Test", "start_time": "06:00", "end_time": "09:00"},
    )

    resp = client.put(
        "/update_playlist/Test",
        json={"new_name": "Updated", "start_time": "10:00", "end_time": "10:00"},
    )
    assert resp.status_code == 400
    assert "cannot be the same" in resp.get_json().get("error", "")


def test_update_playlist_allows_overnight_window(client: FlaskClient) -> None:
    client.post(
        "/create_playlist",
        json={"playlist_name": "Overnight", "start_time": "06:00", "end_time": "09:00"},
    )
    resp = client.put(
        "/update_playlist/Overnight",
        json={"new_name": "Overnight", "start_time": "22:00", "end_time": "05:00"},
    )
    assert resp.status_code == 200


def test_delete_playlist_missing_name(client: FlaskClient) -> None:
    resp = client.delete("/delete_playlist/")
    assert resp.status_code == 404  # Flask routing gives 404 for missing path parameter
    # The validation happens at the route level


def test_playlist_edit_plugin_link_encodes_instance_name(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """The row's "Edit plugin" link interpolated the raw instance name into the
    query string, so "Groceries & errands" opened ?instance=Groceries%20 and
    404'd. It must go through url_for so the name is query-encoded."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": "Groceries & errands",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    body = client.get("/playlist").get_data(as_text=True)
    assert "/plugin/clock?instance=Groceries+%26+errands" in body
    assert "?instance=Groceries &amp; errands" not in body

    resp = client.get("/plugin/clock?instance=Groceries+%26+errands")
    assert resp.status_code == 200

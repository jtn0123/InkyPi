import json
from datetime import datetime, timedelta


def test_add_plugin_success_and_duplicate(client):
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


def test_add_plugin_validation_errors(client):
    bad_name = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "Bad-Name",  # hyphen not allowed
                "refreshType": "interval",
                "unit": "minute",
                "interval": 5,
            }
        ),
    }
    r1 = client.post("/add_plugin", data=bad_name)
    assert r1.status_code == 400
    assert "alphanumeric characters and spaces" in r1.get_json().get("error", "")

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
    assert r2.status_code == 400
    assert "Refresh type is required" in r2.get_json().get("error", "")


def test_create_playlist_error_paths(client):
    # End time must be > start time
    resp = client.post(
        "/create_playlist",
        json={"playlist_name": "Bad", "start_time": "09:00", "end_time": "08:00"},
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


def test_update_playlist_errors_and_failure_branch(client, flask_app, monkeypatch):
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


def test_delete_playlist_not_exist(client):
    resp = client.delete("/delete_playlist/NoSuch")
    assert resp.status_code == 400


def test_eta_endpoint_and_request_ids(client, device_config_dev):
    # Build a playlist with 2 plugins
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin({"plugin_id": "weather", "name": "A", "plugin_settings": {}, "refresh": {"interval": 60}})
    pl.add_plugin({"plugin_id": "clock", "name": "B", "plugin_settings": {}, "refresh": {"interval": 60}})
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


def test_format_relative_time_filter_cases():
    from blueprints.playlist import format_relative_time

    now = datetime.now().astimezone()
    # just now
    assert format_relative_time(now.isoformat()) == "just now"

    # minutes ago
    ten_min_ago = (now - timedelta(minutes=10)).isoformat()
    out = format_relative_time(ten_min_ago)
    assert "minutes ago" in out

    # today at
    earlier_today = (now - timedelta(hours=2)).isoformat()
    out2 = format_relative_time(earlier_today)
    assert "today at " in out2

    # yesterday at
    yesterday = (now - timedelta(days=1, hours=1)).isoformat()
    out3 = format_relative_time(yesterday)
    assert "yesterday at " in out3

    # older date formatted with month abbrev
    older = (now - timedelta(days=10)).isoformat()
    out4 = format_relative_time(older)
    # Expect like "Jan 02 at 3:04 PM"; check month abbrev presence by split space
    assert " at " in out4


def test_add_plugin_missing_playlist_name(client):
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
    assert resp.status_code == 400
    assert "Playlist name is required" in resp.get_json().get("error", "")


def test_add_plugin_missing_instance_name(client):
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
    assert resp.status_code == 400
    assert "Instance name is required" in resp.get_json().get("error", "")


def test_add_plugin_missing_refresh_unit(client):
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
    assert resp.status_code == 400
    assert "Refresh interval unit is required" in resp.get_json().get("error", "")


def test_add_plugin_missing_refresh_interval(client):
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
    assert resp.status_code == 400
    assert "Refresh interval is required" in resp.get_json().get("error", "")


def test_add_plugin_missing_refresh_time_scheduled(client):
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
    assert resp.status_code == 400
    assert "Refresh time is required" in resp.get_json().get("error", "")


def test_add_plugin_playlist_manager_failure(client, flask_app, monkeypatch):
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


def test_create_playlist_invalid_json(client):
    resp = client.post("/create_playlist", data="not json")
    assert resp.status_code == 415  # Flask returns 415 for unsupported media type
    # The actual validation happens later, so we test that the endpoint handles it


def test_create_playlist_missing_name(client):
    resp = client.post(
        "/create_playlist", json={"start_time": "06:00", "end_time": "09:00"}
    )
    assert resp.status_code == 400
    assert "Playlist name is required" in resp.get_json().get("error", "")


def test_create_playlist_missing_times(client):
    resp = client.post("/create_playlist", json={"playlist_name": "Test"})
    assert resp.status_code == 400
    assert "Start time and End time are required" in resp.get_json().get("error", "")


def test_create_playlist_playlist_manager_failure(client, flask_app, monkeypatch):
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    monkeypatch.setattr(pm, "add_playlist", lambda *args, **kwargs: False)

    resp = client.post(
        "/create_playlist",
        json={"playlist_name": "Test", "start_time": "06:00", "end_time": "09:00"},
    )
    assert resp.status_code == 500
    assert "Failed to create playlist" in resp.get_json().get("error", "")


def test_create_playlist_exception_handling(client, flask_app, monkeypatch):
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
    assert "An internal error occurred" in resp.get_json().get("error", "")


def test_update_playlist_end_before_start(client):
    # First create a playlist
    client.post(
        "/create_playlist",
        json={"playlist_name": "Test", "start_time": "06:00", "end_time": "09:00"},
    )

    resp = client.put(
        "/update_playlist/Test",
        json={"new_name": "Updated", "start_time": "10:00", "end_time": "09:00"},
    )
    assert resp.status_code == 400
    assert "End time must be greater than start time" in resp.get_json().get(
        "error", ""
    )


def test_delete_playlist_missing_name(client):
    resp = client.delete("/delete_playlist/")
    assert resp.status_code == 404  # Flask routing gives 404 for missing path parameter
    # The validation happens at the route level

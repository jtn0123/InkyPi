# pyright: reportMissingImports=false


def test_playlist_page_renders(client):
    resp = client.get("/playlist")
    assert resp.status_code == 200


def test_create_update_delete_playlist_flow(client):
    # Create
    payload = {"playlist_name": "Morning", "start_time": "06:00", "end_time": "09:00"}
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200

    # Update
    upd = {"new_name": "EarlyMorning", "start_time": "05:00", "end_time": "08:00"}
    resp = client.put("/update_playlist/Morning", json=upd)
    assert resp.status_code == 200

    # Delete
    resp = client.delete("/delete_playlist/EarlyMorning")
    assert resp.status_code == 200


def test_add_plugin_to_playlist_validation(client):
    # Missing fields
    resp = client.post("/add_plugin", data={})
    assert resp.status_code == 500 or resp.status_code == 400


def test_reorder_plugins_endpoint(client, device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin({"plugin_id": "weather", "name": "A", "plugin_settings": {}, "refresh": {"interval": 60}})
    pl.add_plugin({"plugin_id": "clock", "name": "B", "plugin_settings": {}, "refresh": {"interval": 60}})
    device_config_dev.write_config()

    payload = {
        "playlist_name": "Default",
        "ordered": [
            {"plugin_id": "clock", "name": "B"},
            {"plugin_id": "weather", "name": "A"},
        ],
    }
    resp = client.post("/reorder_plugins", json=payload)
    assert resp.status_code == 200
    j = resp.get_json()
    assert j.get("success") is True

    # Verify order updated in memory
    pl2 = pm.get_playlist("Default")
    assert len(pl2.plugins) == 2
    assert pl2.plugins[0].plugin_id == "clock"
    assert pl2.plugins[0].name == "B"


def test_toggle_only_fresh_and_snooze(client, device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin({"plugin_id": "weather", "name": "A", "plugin_settings": {}, "refresh": {"interval": 60}})
    device_config_dev.write_config()

    resp = client.post("/toggle_only_fresh", json={"playlist_name": "Default", "plugin_id": "weather", "plugin_instance": "A", "only_fresh": True})
    assert resp.status_code == 200 and resp.get_json().get("success")

    resp2 = client.post("/set_snooze", json={"playlist_name": "Default", "plugin_id": "weather", "plugin_instance": "A", "snooze_until": None})
    assert resp2.status_code == 200 and resp2.get_json().get("success")

"""JTN-381: /update_plugin_instance must validate the refresh_settings payload.

Previously the route parsed the form, shoved the raw ``refresh_settings``
JSON string into plugin_instance.settings, and returned 200 success —
leaving plugin_instance.refresh untouched so reloading silently reverted
the user's new interval while the modal showed a green success toast.
"""

import json


def _setup_playlist_for_instance(device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    if not pm.find_plugin("ai_text", "Inst One"):
        pl.add_plugin(
            {
                "plugin_id": "ai_text",
                "name": "Inst One",
                "plugin_settings": {},
                "refresh": {"interval": 300},
            }
        )
    device_config_dev.write_config()


def _put(client, instance_name, refresh_settings, extra=None):
    # ai_text requires textPrompt + textModel — supply sensible defaults so the
    # existing required-field validator doesn't mask what we're testing here.
    data = {
        "plugin_id": "ai_text",
        "textPrompt": "hello world",
        "textModel": "gpt-4o-mini",
        "refresh_settings": json.dumps(refresh_settings),
    }
    if extra:
        data.update(extra)
    return client.put(f"/update_plugin_instance/{instance_name}", data=data)


def test_update_plugin_instance_rejects_interval_above_max(client, device_config_dev):
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "5000", "unit": "minute"},
    )
    assert resp.status_code == 422
    body = resp.get_json() or {}
    assert body.get("success") is False
    assert "between 1 and 999" in (body.get("message") or body.get("error") or "")

    pm = device_config_dev.get_playlist_manager()
    inst = pm.find_plugin("ai_text", "Inst One")
    assert inst is not None
    # Refresh config must be unchanged from the fixture default.
    assert inst.refresh == {"interval": 300}


def test_update_plugin_instance_rejects_interval_below_min(client, device_config_dev):
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "0", "unit": "minute"},
    )
    assert resp.status_code == 422
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 300}


def test_update_plugin_instance_rejects_non_numeric_interval(client, device_config_dev):
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "abc", "unit": "minute"},
    )
    assert resp.status_code == 422
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 300}


def test_update_plugin_instance_rejects_invalid_unit(client, device_config_dev):
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "15", "unit": "century"},
    )
    assert resp.status_code == 422
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 300}


def test_update_plugin_instance_accepts_valid_interval(client, device_config_dev):
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "15", "unit": "minute"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 15 * 60}


def test_update_plugin_instance_accepts_valid_scheduled(client, device_config_dev):
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "scheduled", "refreshTime": "09:30"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"scheduled": "09:30"}


def test_update_plugin_instance_rejects_malformed_json_refresh_settings(
    client, device_config_dev
):
    _setup_playlist_for_instance(device_config_dev)
    resp = client.put(
        "/update_plugin_instance/Inst One",
        data={
            "plugin_id": "ai_text",
            "textPrompt": "hello world",
            "textModel": "gpt-4o-mini",
            "refresh_settings": "not valid json",
        },
    )
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False

    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 300}


def test_update_plugin_instance_without_refresh_settings_still_works(
    client, device_config_dev
):
    """Callers that don't send refresh_settings (e.g. older flows) must not
    hit the new validator. The refresh config stays unchanged."""
    _setup_playlist_for_instance(device_config_dev)
    resp = client.put(
        "/update_plugin_instance/Inst One",
        data={
            "plugin_id": "ai_text",
            "textPrompt": "hello world",
            "textModel": "gpt-4o-mini",
        },
    )
    assert resp.status_code == 200
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 300}

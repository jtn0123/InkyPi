"""JTN-381: /update_plugin_instance must validate the refresh_settings payload.

Previously the route parsed the form, shoved the raw ``refresh_settings``
JSON string into plugin_instance.settings, and returned 200 success —
leaving plugin_instance.refresh untouched so reloading silently reverted
the user's new interval while the modal showed a green success toast.
"""

import json
from typing import Any

from flask.testing import FlaskClient


def _setup_playlist_for_instance(device_config_dev: Any) -> None:
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


def _put(
    client: FlaskClient, instance_name: Any, refresh_settings: Any, extra: Any = None
) -> Any:
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


def test_update_plugin_instance_rejects_interval_above_max(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_update_plugin_instance_rejects_interval_below_min(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "0", "unit": "minute"},
    )
    assert resp.status_code == 422
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 300}


def test_update_plugin_instance_rejects_non_numeric_interval(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "abc", "unit": "minute"},
    )
    assert resp.status_code == 422
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 300}


def test_update_plugin_instance_rejects_invalid_unit(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "15", "unit": "century"},
    )
    assert resp.status_code == 422
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 300}


def test_update_plugin_instance_accepts_valid_interval(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _setup_playlist_for_instance(device_config_dev)
    resp = _put(
        client,
        "Inst One",
        {"refreshType": "interval", "interval": "15", "unit": "minute"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    pm = device_config_dev.get_playlist_manager()
    assert pm.find_plugin("ai_text", "Inst One").refresh == {"interval": 15 * 60}


def test_update_plugin_instance_accepts_valid_scheduled(
    client: FlaskClient, device_config_dev: Any
) -> None:
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
    client: FlaskClient, device_config_dev: Any
) -> None:
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
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_refresh_only_edit_does_not_wipe_plugin_settings(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """The playlist page's "Edit refresh settings" modal (actions.js
    saveRefreshSettings) posts only plugin_id + refresh_settings — no
    plugin-specific fields — so plugin_settings parses to {} for that
    request alone. update_plugin_instance previously overwrote
    plugin_instance.settings with that empty dict unconditionally, silently
    deleting the instance's real settings on every schedule-only edit.
    """
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock Inst",
            "plugin_settings": {"selectedClockFace": "digital"},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    # Mirrors saveRefreshSettings' actual payload: plugin_id + refresh_settings
    # only, nothing else.
    resp = client.put(
        "/update_plugin_instance/Clock Inst",
        data={
            "plugin_id": "clock",
            "refresh_settings": json.dumps(
                {"refreshType": "interval", "interval": "20", "unit": "minute"}
            ),
        },
    )
    assert resp.status_code == 200

    instance = pm.find_plugin("clock", "Clock Inst")
    assert instance.refresh == {"interval": 1200}
    assert instance.settings == {"selectedClockFace": "digital"}

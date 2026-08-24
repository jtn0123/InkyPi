"""Routes for creating and editing native composite screens: GET
/composite_screen/new, POST /add_composite_screen, GET
/composite_screen/edit/<name>, PUT /update_composite_screen/<name>.
"""

import json
from typing import Any

from flask.testing import FlaskClient

REGIONS = [
    {"plugin_id": "clock", "x": 0, "y": 0, "w": 400, "h": 480, "settings": {}},
    {
        "plugin_id": "countdown",
        "x": 400,
        "y": 0,
        "w": 400,
        "h": 480,
        "settings": {"title": "New Year"},
    },
]


def _ensure_default_playlist(device_config_dev: Any) -> None:
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
        device_config_dev.write_config()


def _add_composite(
    client: FlaskClient, instance_name: str, regions: list[dict[str, Any]] = REGIONS
) -> Any:
    return client.post(
        "/add_composite_screen",
        data={
            "regionsJson": json.dumps(regions),
            "refresh_settings": json.dumps(
                {
                    "playlist": "Default",
                    "instance_name": instance_name,
                    "refreshType": "interval",
                    "interval": "10",
                    "unit": "minute",
                }
            ),
        },
    )


def test_new_composite_screen_page_renders(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    resp = client.get("/composite_screen/new")
    assert resp.status_code == 200
    assert b"compositeForm" in resp.data
    assert b"Add to Playlist" in resp.data


def test_add_composite_screen_creates_instance_with_regions(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    resp = _add_composite(client, "My Composite")
    assert resp.status_code == 200, resp.get_json()

    pm = device_config_dev.get_playlist_manager()
    from model import COMPOSITE_PLUGIN_ID

    instance = pm.find_plugin(COMPOSITE_PLUGIN_ID, "My Composite")
    assert instance is not None
    assert instance.settings["regions"][0]["plugin_id"] == "clock"
    assert instance.settings["regions"][1]["settings"]["title"] == "New Year"
    assert instance.refresh == {"interval": 600}


def test_add_composite_screen_rejects_empty_regions(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    resp = _add_composite(client, "Empty Composite", regions=[])
    assert resp.status_code == 422
    body = resp.get_json() or {}
    assert body.get("success") is False


def test_add_composite_screen_rejects_out_of_bounds_region(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    bad_regions = [
        {"plugin_id": "clock", "x": 700, "y": 0, "w": 200, "h": 60, "settings": {}}
    ]
    resp = _add_composite(client, "OOB Composite", regions=bad_regions)
    assert resp.status_code == 422
    body = resp.get_json() or {}
    assert "exceeds" in (body.get("message") or body.get("error") or "")


def test_add_composite_screen_rejects_unregistered_plugin(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    bad_regions = [
        {
            "plugin_id": "does_not_exist",
            "x": 0,
            "y": 0,
            "w": 100,
            "h": 60,
            "settings": {},
        }
    ]
    resp = _add_composite(client, "Bad Plugin Composite", regions=bad_regions)
    assert resp.status_code == 422
    body = resp.get_json() or {}
    assert "not installed" in (body.get("message") or body.get("error") or "")


def test_edit_composite_screen_page_prefills_regions(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    assert _add_composite(client, "Edit Me").status_code == 200

    resp = client.get("/composite_screen/edit/Edit Me")
    assert resp.status_code == 200
    assert b"Save regions" in resp.data
    assert b'"plugin_id": "clock"' in resp.data or b'"plugin_id":"clock"' in resp.data


def test_edit_composite_screen_page_404s_for_unknown_instance(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    resp = client.get("/composite_screen/edit/Does Not Exist")
    assert resp.status_code == 404


def test_update_composite_screen_persists_new_regions(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    assert _add_composite(client, "Update Me").status_code == 200

    new_regions = [
        {"plugin_id": "clock", "x": 0, "y": 0, "w": 800, "h": 480, "settings": {}}
    ]
    resp = client.put(
        "/update_composite_screen/Update Me",
        data={"regionsJson": json.dumps(new_regions)},
    )
    assert resp.status_code == 200, resp.get_json()

    pm = device_config_dev.get_playlist_manager()
    from model import COMPOSITE_PLUGIN_ID

    instance = pm.find_plugin(COMPOSITE_PLUGIN_ID, "Update Me")
    assert len(instance.settings["regions"]) == 1
    assert instance.settings["regions"][0]["w"] == 800
    # Refresh cadence is untouched by this route -- it's edited through the
    # same generic modal every plugin instance uses.
    assert instance.refresh == {"interval": 600}


def test_update_composite_screen_404s_for_unknown_instance(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    resp = client.put(
        "/update_composite_screen/Does Not Exist",
        data={"regionsJson": json.dumps(REGIONS)},
    )
    assert resp.status_code == 404


def test_update_composite_screen_rejects_invalid_region_shape(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _ensure_default_playlist(device_config_dev)
    assert _add_composite(client, "Shape Guard").status_code == 200

    bad_regions = [
        {"plugin_id": "clock", "x": -5, "y": 0, "w": 100, "h": 60, "settings": {}}
    ]
    resp = client.put(
        "/update_composite_screen/Shape Guard",
        data={"regionsJson": json.dumps(bad_regions)},
    )
    assert resp.status_code == 422

    pm = device_config_dev.get_playlist_manager()
    from model import COMPOSITE_PLUGIN_ID

    # Original regions must be untouched after a rejected update.
    instance = pm.find_plugin(COMPOSITE_PLUGIN_ID, "Shape Guard")
    assert len(instance.settings["regions"]) == 2

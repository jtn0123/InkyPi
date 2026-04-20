# pyright: reportMissingImports=false
"""Security regression coverage for privileged device-admin flows.

The shared ``client`` fixture intentionally skips production CSRF enforcement
and does not enable PIN auth so most tests can stay lightweight. This suite
re-enables the real middleware on top of that production app bootstrap and
verifies that privileged routes require the right combination of auth + CSRF.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass

import pytest

PIN = "246810"
READONLY_TOKEN = "readonly-monitor-token"
VALID_CSRF = "privileged-flow-csrf-token"


@dataclass(frozen=True)
class FlowCase:
    name: str
    method: str
    path: str
    kwargs: dict


PRIVILEGED_GET_CASES = (
    FlowCase("settings-export-get", "GET", "/settings/export", {}),
    FlowCase("plugin-export-get", "GET", "/api/plugins/export", {}),
)

PRIVILEGED_POST_CASES = (
    FlowCase("shutdown", "POST", "/shutdown", {"json": {"reboot": False}}),
    FlowCase("update", "POST", "/settings/update", {}),
    FlowCase("rollback", "POST", "/settings/update/rollback", {}),
    FlowCase(
        "settings-import",
        "POST",
        "/settings/import",
        {"json": {"config": {"name": "Imported Device"}}},
    ),
    FlowCase(
        "settings-export-post",
        "POST",
        "/settings/export",
        {"json": {"include_keys": True}},
    ),
    FlowCase(
        "save-api-keys",
        "POST",
        "/settings/save_api_keys",
        {"data": {"OPEN_AI_SECRET": "sk-test-secret"}},
    ),
    FlowCase(
        "delete-api-key",
        "POST",
        "/settings/delete_api_key",
        {"data": {"key": "OPEN_AI_SECRET"}},
    ),
    FlowCase(
        "plugin-import",
        "POST",
        "/api/plugins/import",
        {
            "json": {
                "version": 1,
                "instances": [
                    {"plugin_id": "clock", "name": "Imported Clock", "settings": {}}
                ],
            }
        },
    ),
)

ALL_CASES = PRIVILEGED_GET_CASES + PRIVILEGED_POST_CASES


def _bearer_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {READONLY_TOKEN}"}


def _request(case: FlowCase, client, *, headers: dict[str, str] | None = None):
    kwargs = deepcopy(case.kwargs)
    if headers:
        merged_headers = dict(kwargs.get("headers", {}))
        merged_headers.update(headers)
        kwargs["headers"] = merged_headers
    method = getattr(client, case.method.lower())
    return method(case.path, **kwargs)


def _seed_authed_session(client, *, csrf_token: str | None = VALID_CSRF) -> None:
    with client.session_transaction() as sess:
        sess["authed"] = True
        if csrf_token is not None:
            sess["_csrf_token"] = csrf_token


def _csrf_headers(token: str = VALID_CSRF) -> dict[str, str]:
    return {"X-CSRFToken": token}


def _write_failure_record(tmp_path) -> None:
    payload = {
        "timestamp": "2026-04-14T23:00:00Z",
        "exit_code": 97,
        "last_command": "apt_install",
        "recent_journal_lines": "apt-get: failed",
    }
    (tmp_path / ".last-update-failure").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_prev_version(tmp_path, value: str = "v0.52.0") -> None:
    (tmp_path / "prev_version").write_text(value, encoding="utf-8")


def _add_plugin_instance(device_config, plugin_id="clock", name="My Clock") -> None:
    pm = device_config.get_playlist_manager()
    playlist = pm.get_playlist("Default")
    if not playlist:
        pm.add_playlist("Default")
        playlist = pm.get_playlist("Default")
    playlist.add_plugin(
        {
            "plugin_id": plugin_id,
            "name": name,
            "refresh": {"interval": 3600},
            "plugin_settings": {"time_format": "24h"},
        }
    )
    device_config.write_config()


@pytest.fixture()
def privileged_client(client, monkeypatch):
    """Enable real PIN auth + real CSRF middleware on the production test app."""
    monkeypatch.setenv("INKYPI_AUTH_PIN", PIN)
    monkeypatch.setenv("INKYPI_READONLY_TOKEN", READONLY_TOKEN)

    from app_setup.auth import init_auth
    from inkypi import _setup_csrf_protection

    app = client.application
    init_auth(app, app.config["DEVICE_CONFIG"])
    _setup_csrf_protection(app)
    return client


@pytest.fixture(autouse=True)
def reset_privileged_flow_state():
    import blueprints.settings as settings_mod

    settings_mod._set_update_state(False, None)
    settings_mod._shutdown_limiter.reset()
    yield
    settings_mod._set_update_state(False, None)
    settings_mod._shutdown_limiter.reset()


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.name)
def test_unauthenticated_privileged_flows_redirect_to_login(privileged_client, case):
    resp = _request(case, privileged_client)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.name)
def test_readonly_token_cannot_access_privileged_flows(privileged_client, case):
    resp = _request(case, privileged_client, headers=_bearer_headers())
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


@pytest.mark.parametrize("case", PRIVILEGED_POST_CASES, ids=lambda case: case.name)
def test_authenticated_privileged_posts_still_require_csrf(privileged_client, case):
    _seed_authed_session(privileged_client, csrf_token=VALID_CSRF)

    resp = _request(case, privileged_client)

    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert "CSRF token missing or invalid" in data["error"]


def test_authenticated_session_can_export_settings(privileged_client):
    _seed_authed_session(privileged_client)

    resp = privileged_client.get("/settings/export")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "config" in data["data"]


def test_authenticated_session_can_export_settings_with_keys_when_csrf_present(
    privileged_client, device_config_dev
):
    _seed_authed_session(privileged_client)
    device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-exportable")

    resp = privileged_client.post(
        "/settings/export",
        json={"include_keys": True},
        headers=_csrf_headers(),
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["env_keys"]["OPEN_AI_SECRET"] == "sk-exportable"


def test_authenticated_session_can_import_settings_with_csrf(
    privileged_client, device_config_dev
):
    _seed_authed_session(privileged_client)

    resp = privileged_client.post(
        "/settings/import",
        json={"config": {"name": "Imported Device", "timezone": "UTC"}},
        headers=_csrf_headers(),
    )

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert device_config_dev.get_config("name") == "Imported Device"


def test_authenticated_session_can_save_and_delete_api_keys_with_csrf(
    privileged_client, device_config_dev
):
    _seed_authed_session(privileged_client)

    save_resp = privileged_client.post(
        "/settings/save_api_keys",
        data={"OPEN_AI_SECRET": "sk-secure"},
        headers=_csrf_headers(),
    )
    assert save_resp.status_code == 200
    assert "OPEN_AI_SECRET" in save_resp.get_json()["updated"]
    assert device_config_dev.load_env_key("OPEN_AI_SECRET") == "sk-secure"

    delete_resp = privileged_client.post(
        "/settings/delete_api_key",
        data={"key": "OPEN_AI_SECRET"},
        headers=_csrf_headers(),
    )
    assert delete_resp.status_code == 200
    assert delete_resp.get_json()["success"] is True
    assert device_config_dev.load_env_key("OPEN_AI_SECRET") in (None, "")


def test_authenticated_session_can_shutdown_with_csrf(privileged_client, monkeypatch):
    import blueprints.settings as settings_mod

    _seed_authed_session(privileged_client)

    calls: list[list[str]] = []

    def _fake_run(argv, check):
        calls.append(list(argv))

    monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)

    resp = privileged_client.post(
        "/shutdown",
        json={"reboot": False},
        headers=_csrf_headers(),
    )

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert calls == [["sudo", "shutdown", "-h", "now"]]


def test_authenticated_session_can_start_update_with_csrf(privileged_client, monkeypatch):
    import blueprints.settings as settings_mod

    _seed_authed_session(privileged_client)

    monkeypatch.setattr(settings_mod, "_systemd_available", lambda: False)
    monkeypatch.setattr(settings_mod, "_get_update_script_path", lambda: None)
    monkeypatch.setattr(
        settings_mod,
        "_start_update_fallback_thread",
        lambda script_path, target_tag=None: None,
    )

    resp = privileged_client.post(
        "/settings/update",
        headers=_csrf_headers(),
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["running"] is True


def test_authenticated_session_can_start_rollback_with_csrf(
    privileged_client, monkeypatch, tmp_path
):
    import blueprints.settings as settings_mod

    _seed_authed_session(privileged_client)
    monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
    _write_failure_record(tmp_path)
    _write_prev_version(tmp_path)
    monkeypatch.setattr(settings_mod, "_systemd_available", lambda: False)
    monkeypatch.setattr(
        settings_mod,
        "_start_update_fallback_thread",
        lambda script_path, target_tag=None: None,
    )

    resp = privileged_client.post(
        "/settings/update/rollback",
        headers=_csrf_headers(),
    )

    assert resp.status_code == 202
    data = resp.get_json()
    assert data["success"] is True
    assert data["running"] is True
    assert data["target_version"] == "v0.52.0"


def test_authenticated_session_can_export_plugins(privileged_client, device_config_dev):
    _seed_authed_session(privileged_client)
    _add_plugin_instance(device_config_dev, name="Secure Export Clock")

    resp = privileged_client.get("/api/plugins/export")

    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    body = json.loads(resp.data)
    assert any(item["name"] == "Secure Export Clock" for item in body["instances"])


def test_authenticated_session_can_import_plugins_with_csrf(
    privileged_client, device_config_dev
):
    _seed_authed_session(privileged_client)

    resp = privileged_client.post(
        "/api/plugins/import",
        json={
            "version": 1,
            "exported_at": "2026-04-19T00:00:00+00:00",
            "instances": [
                {
                    "plugin_id": "clock",
                    "name": "Secure Import Clock",
                    "settings": {"time_format": "12h"},
                }
            ],
        },
        headers=_csrf_headers(),
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["imported"] == 1

    pm = device_config_dev.get_playlist_manager()
    imported = pm.find_plugin("clock", "Secure Import Clock")
    assert imported is not None
    assert imported.settings.get("time_format") == "12h"

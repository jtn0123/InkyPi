import time


def test_settings_update_systemd_and_fallback(client, monkeypatch):
    from blueprints import settings as settings_mod

    # Ensure clean state
    settings_mod._set_update_state(False, None)

    # Make systemd available and then force systemd-run failure to trigger fallback
    monkeypatch.setattr(settings_mod, "_systemd_available", lambda: True, raising=True)

    called = {"systemd": False, "thread": False}

    def fake_systemd(unit_name, script_path):
        called["systemd"] = True
        raise RuntimeError("systemd-run failed")

    def fake_thread(script_path):
        called["thread"] = True
        # Do not actually sleep inside the worker; immediately clear running state
        settings_mod._set_update_state(False, None)

    monkeypatch.setattr(settings_mod, "_start_update_via_systemd", fake_systemd, raising=True)
    monkeypatch.setattr(settings_mod, "_start_update_fallback_thread", fake_thread, raising=True)

    # Start update
    r = client.post("/settings/update")
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert data["running"] is True
    assert called["systemd"] is True
    assert called["thread"] is True  # Fell back

    # Status should flip to not running quickly (our fake thread clears it immediately)
    r2 = client.get("/settings/update_status")
    assert r2.status_code == 200
    st = r2.get_json()
    assert st["running"] is False


def test_settings_update_duplicate_returns_409(client, monkeypatch):
    from blueprints import settings as settings_mod

    # Ensure clean state
    settings_mod._set_update_state(False, None)

    # Force non-systemd path to use thread runner
    monkeypatch.setattr(settings_mod, "_systemd_available", lambda: False, raising=True)

    # Make fallback thread just mark running and keep it until we check 409
    def fake_thread(script_path):
        # Mark running and do not clear
        settings_mod._set_update_state(True, None)

    monkeypatch.setattr(settings_mod, "_start_update_fallback_thread", fake_thread, raising=True)

    r1 = client.post("/settings/update")
    assert r1.status_code == 200
    data1 = r1.get_json()
    assert data1["running"] is True

    # Second call should see running and respond 409
    r2 = client.post("/settings/update")
    assert r2.status_code == 409
    data2 = r2.get_json()
    assert data2["running"] is True


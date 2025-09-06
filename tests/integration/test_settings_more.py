# pyright: reportMissingImports=false
import io


def test_shutdown_route_logs_and_returns_json(client, monkeypatch):
    calls = {"cmd": None}
    monkeypatch.setattr("os.system", lambda cmd: calls.update(cmd=cmd))

    resp = client.post('/shutdown', json={"reboot": False})
    assert resp.status_code == 200
    assert resp.json.get("success") is True
    assert isinstance(calls["cmd"], str)


def test_download_logs_dev_mode_message(client, monkeypatch):
    # Force JOURNAL_AVAILABLE = False path by re-importing module symbol
    import blueprints.settings as settings_mod
    monkeypatch.setattr(settings_mod, "JOURNAL_AVAILABLE", False)

    resp = client.get('/download-logs?hours=1')
    assert resp.status_code == 200
    assert b"Log download not available" in resp.data



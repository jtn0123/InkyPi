# pyright: reportMissingImports=false
import io
import json


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


def test_api_logs_basic(client, monkeypatch):
    # Force JOURNAL_AVAILABLE False path so response is deterministic
    import blueprints.settings as settings_mod
    monkeypatch.setattr(settings_mod, 'JOURNAL_AVAILABLE', False)

    resp = client.get('/api/logs')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'lines' in data and isinstance(data['lines'], list)
    assert 'count' in data and isinstance(data['count'], int)
    assert 'meta' in data and data['meta']['hours'] >= 1


def test_api_logs_filters_and_limits(client, monkeypatch):
    # Stub _read_log_lines to a fixed corpus
    import blueprints.settings as settings_mod

    def fake_read(hours: int):
        return [
            'Jan 01 host app[1]: INFO started',
            'Jan 01 host app[1]: WARNING something odd',
            'Jan 01 host app[1]: ERROR failure occurred',
            'Jan 01 host app[1]: DEBUG noisy',
        ]

    monkeypatch.setattr(settings_mod, '_read_log_lines', fake_read)

    resp = client.get('/api/logs?level=warn_errors&limit=2')
    assert resp.status_code == 200
    data = resp.get_json()
    # Only WARNING and ERROR should remain, limited to 2
    assert data['count'] == 2
    for line in data['lines']:
        assert ('WARNING' in line) or ('ERROR' in line)

    # contains filter
    resp2 = client.get('/api/logs?contains=started&level=all')
    data2 = resp2.get_json()
    assert data2['count'] == 1
    assert 'started' in data2['lines'][0]


def test_api_logs_guardrails(client, monkeypatch):
    import blueprints.settings as settings_mod

    # very large fake corpus to trigger size trimming
    big_line = 'X' * 4096
    corpus = [f'Jan 01 host app[1]: ERROR {big_line} #{i}' for i in range(1000)]

    monkeypatch.setattr(settings_mod, '_read_log_lines', lambda h: corpus)

    resp = client.get('/api/logs?hours=9999&limit=999999&level=errors&contains=' + ('a'*500))
    assert resp.status_code == 200
    data = resp.get_json()
    # Hours and limit should be clamped, contains truncated, and response not empty
    assert 1 <= data['meta']['hours'] <= 24
    assert 50 <= data['meta']['limit'] <= 2000
    assert data['count'] <= data['meta']['limit']
    assert data['truncated'] is True



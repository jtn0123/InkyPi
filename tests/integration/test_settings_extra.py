import io


def test_delete_api_key_invalid(client):
    resp = client.post('/settings/delete_api_key', data={'key': 'NOT_A_REAL_KEY'})
    assert resp.status_code == 400


def test_save_settings_zero_interval_rejected(client):
    data = {
        'deviceName': 'D',
        'orientation': 'horizontal',
        'invertImage': '',
        'logSystemStats': '',
        'timezoneName': 'UTC',
        'timeFormat': '24h',
        'interval': '0',  # numeric but invalid by bounds check
        'unit': 'minute',
        'saturation': '1.0',
        'brightness': '1.0',
        'sharpness': '1.0',
        'contrast': '1.0',
    }
    resp = client.post('/save_settings', data=data)
    assert resp.status_code == 400


def test_shutdown_reboot_path(client, monkeypatch):
    calls = {"cmd": None}
    monkeypatch.setattr("os.system", lambda cmd: calls.update(cmd=cmd))

    resp = client.post('/shutdown', json={"reboot": True})
    assert resp.status_code == 200
    assert 'reboot' in (calls["cmd"] or '')


def test_download_logs_has_attachment_header(client, monkeypatch):
    import blueprints.settings as settings_mod
    monkeypatch.setattr(settings_mod, "JOURNAL_AVAILABLE", False)
    resp = client.get('/download-logs?hours=2')
    assert resp.status_code == 200
    cd = resp.headers.get('Content-Disposition', '')
    assert 'attachment;' in cd and 'inkypi_' in cd and cd.endswith('.log') is False
    # Ends with dynamic timestamp, but should include .log in filename value
    assert '.log' in cd


def test_api_logs_rate_limited(client, monkeypatch):
    import blueprints.settings as settings_mod
    monkeypatch.setattr(settings_mod, '_rate_limit_ok', lambda remote: False)
    resp = client.get('/api/logs')
    assert resp.status_code == 429


def test_api_logs_errors_level_filter(client, monkeypatch):
    import blueprints.settings as settings_mod

    def fake_read(hours: int):
        return [
            'Jan 01 host app[1]: INFO started',
            'Jan 01 host app[1]: WARNING warn',
            'Jan 01 host app[1]: ERROR broke',
            'Jan 01 host app[1]: critical CRITICAL boom',
        ]

    monkeypatch.setattr(settings_mod, '_read_log_lines', fake_read)
    resp = client.get('/api/logs?level=errors')
    assert resp.status_code == 200
    lines = resp.get_json()['lines']
    assert all(('ERROR' in ln) or ('CRITICAL' in ln.upper()) or ('Exception' in ln) for ln in lines)


import json
from datetime import datetime, timedelta


def test_add_plugin_success_and_duplicate(client):
    payload = {
        'plugin_id': 'clock',
        'refresh_settings': json.dumps({
            'playlist': 'Default',
            'instance_name': 'My Clock',
            'refreshType': 'interval',
            'unit': 'minute',
            'interval': 10,
        }),
    }
    resp = client.post('/add_plugin', data=payload)
    assert resp.status_code == 200
    assert resp.get_json().get('success') is True

    # Duplicate should be rejected
    resp2 = client.post('/add_plugin', data=payload)
    assert resp2.status_code == 400
    assert 'already exists' in resp2.get_json().get('error', '')


def test_add_plugin_validation_errors(client):
    bad_name = {
        'plugin_id': 'clock',
        'refresh_settings': json.dumps({
            'playlist': 'Default',
            'instance_name': 'Bad-Name',  # hyphen not allowed
            'refreshType': 'interval',
            'unit': 'minute',
            'interval': 5,
        }),
    }
    r1 = client.post('/add_plugin', data=bad_name)
    assert r1.status_code == 400
    assert 'alphanumeric characters and spaces' in r1.get_json().get('error', '')

    missing_type = {
        'plugin_id': 'clock',
        'refresh_settings': json.dumps({
            'playlist': 'Default',
            'instance_name': 'X',
            # missing refreshType
        }),
    }
    r2 = client.post('/add_plugin', data=missing_type)
    assert r2.status_code == 400
    assert 'Refresh type is required' in r2.get_json().get('error', '')


def test_create_playlist_error_paths(client):
    # End time must be > start time
    resp = client.post('/create_playlist', json={
        'playlist_name': 'Bad', 'start_time': '09:00', 'end_time': '08:00'
    })
    assert resp.status_code == 400

    # Missing JSON
    resp2 = client.post('/create_playlist')
    assert resp2.status_code == 400

    # Duplicate name
    ok = client.post('/create_playlist', json={
        'playlist_name': 'Dupe', 'start_time': '06:00', 'end_time': '07:00'
    })
    assert ok.status_code == 200
    dupe = client.post('/create_playlist', json={
        'playlist_name': 'Dupe', 'start_time': '06:00', 'end_time': '07:00'
    })
    assert dupe.status_code == 400


def test_update_playlist_errors_and_failure_branch(client, flask_app, monkeypatch):
    # Missing required fields
    r = client.put('/update_playlist/Nope', json={})
    assert r.status_code == 400

    # Not found
    r2 = client.put('/update_playlist/Nope', json={
        'new_name': 'New', 'start_time': '01:00', 'end_time': '02:00'
    })
    assert r2.status_code == 400

    # Create then force update to return False to hit 500 branch
    client.post('/create_playlist', json={
        'playlist_name': 'X', 'start_time': '01:00', 'end_time': '02:00'
    })

    pm = flask_app.config['DEVICE_CONFIG'].get_playlist_manager()
    monkeypatch.setattr(pm, 'update_playlist', lambda *args, **kwargs: False)

    r3 = client.put('/update_playlist/X', json={
        'new_name': 'Y', 'start_time': '01:00', 'end_time': '02:00'
    })
    assert r3.status_code == 500


def test_delete_playlist_not_exist(client):
    resp = client.delete('/delete_playlist/NoSuch')
    assert resp.status_code == 400


def test_format_relative_time_filter_cases():
    from blueprints.playlist import format_relative_time

    now = datetime.now().astimezone()
    # just now
    assert format_relative_time(now.isoformat()) == 'just now'

    # minutes ago
    ten_min_ago = (now - timedelta(minutes=10)).isoformat()
    out = format_relative_time(ten_min_ago)
    assert 'minutes ago' in out

    # today at
    earlier_today = (now - timedelta(hours=2)).isoformat()
    out2 = format_relative_time(earlier_today)
    assert 'today at ' in out2

    # yesterday at
    yesterday = (now - timedelta(days=1, hours=1)).isoformat()
    out3 = format_relative_time(yesterday)
    assert 'yesterday at ' in out3

    # older date formatted with month abbrev
    older = (now - timedelta(days=10)).isoformat()
    out4 = format_relative_time(older)
    # Expect like "Jan 02 at 3:04 PM"; check month abbrev presence by split space
    assert ' at ' in out4


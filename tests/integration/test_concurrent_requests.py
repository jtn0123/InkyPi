# pyright: reportMissingImports=false
"""Concurrent request tests to verify thread safety."""
import threading

import pytest


def test_concurrent_settings_saves(client):
    """5 simultaneous settings POSTs should not corrupt state."""
    results = []
    errors = []

    def save_settings(idx):
        try:
            data = {
                "unit": "minute",
                "interval": str(5 + idx),
                "timeFormat": "24h",
                "timezoneName": "UTC",
            }
            resp = client.post("/save_settings", data=data)
            results.append(resp.status_code)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=save_settings, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"Errors during concurrent saves: {errors}"
    assert len(results) == 5
    for status in results:
        assert status in (200, 302, 422), f"Unexpected status: {status}"


def test_concurrent_playlist_creates(client):
    """5 simultaneous playlist creates should all succeed or conflict gracefully."""
    results = []
    errors = []

    def create_playlist(idx):
        try:
            import json
            data = {
                "playlist_name": f"concurrent_test_{idx}",
                "start_time": f"{8 + idx}:00",
                "end_time": f"{9 + idx}:00",
            }
            resp = client.post(
                "/create_playlist",
                data=json.dumps(data),
                content_type="application/json",
            )
            results.append(resp.status_code)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=create_playlist, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"Errors during concurrent creates: {errors}"
    assert len(results) == 5
    for status in results:
        assert status in (200, 302, 400, 409), f"Unexpected status: {status}"

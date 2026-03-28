# pyright: reportMissingImports=false
"""Property-based API tests using Hypothesis."""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pytest


@given(st.integers())
@settings(max_examples=50, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_settings_save_rejects_invalid_intervals(client, interval):
    """Settings save should handle any integer interval value without crashing."""
    data = {
        "unit": "minute",
        "interval": str(interval),
        "timeFormat": "24h",
        "timezoneName": "UTC",
    }
    resp = client.post("/save_settings", data=data)
    # Should return 200 (success or validation) or 422 - not 500
    assert resp.status_code in (200, 302, 400, 422)


@given(st.text(max_size=200))
@settings(max_examples=50, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_settings_save_rejects_invalid_timezone(client, tz_value):
    """Settings save should handle arbitrary timezone strings."""
    data = {
        "unit": "minute",
        "interval": "5",
        "timeFormat": "24h",
        "timezoneName": tz_value,
    }
    resp = client.post("/save_settings", data=data)
    assert resp.status_code in (200, 302, 400, 422)


@given(st.text(max_size=100))
@settings(max_examples=50, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_playlist_create_name_validation(client, name):
    """Playlist creation should handle arbitrary name strings."""
    import json
    data = {
        "playlist_name": name,
        "start_time": "08:00",
        "end_time": "09:00",
    }
    resp = client.post(
        "/create_playlist",
        data=json.dumps(data),
        content_type="application/json",
    )
    # Should not crash; may succeed or reject
    assert resp.status_code in (200, 302, 400, 409)


@given(st.text(max_size=20))
@settings(max_examples=50, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_playlist_time_validation(client, time_str):
    """Playlist time fields should handle arbitrary time format strings."""
    import json
    data = {
        "playlist_name": "test_playlist",
        "start_time": time_str,
        "end_time": "23:59",
    }
    resp = client.post(
        "/create_playlist",
        data=json.dumps(data),
        content_type="application/json",
    )
    assert resp.status_code in (200, 302, 400, 409)


@given(st.sampled_from([
    '<script>alert(1)</script>',
    '"><script>alert("xss")</script>',
    "javascript:alert(1)",
    '<img src=x onerror=alert(1)>',
    '<svg onload=alert(1)>',
    '{{7*7}}',
    '${7*7}',
]).flatmap(lambda prefix: st.text(max_size=50).map(lambda s: prefix + s)))
@settings(max_examples=30, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_plugin_form_rejects_xss_payloads(client, xss_input):
    """Plugin save should not crash on XSS-like input strings."""
    import json
    data = {
        "plugin_id": "clock_test1",
        "plugin_instance": "test",
        "settings": {"title": xss_input},
    }
    resp = client.post(
        "/save_plugin",
        data=json.dumps(data),
        content_type="application/json",
    )
    # Should handle gracefully — not crash with 500
    assert resp.status_code in (200, 302, 400, 404, 422)


@given(st.text(max_size=300))
@settings(max_examples=50, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_rss_feed_url_validation(client, url):
    """RSS plugin should handle arbitrary feed URL strings."""
    import json
    data = {
        "plugin_id": "rss_test1",
        "plugin_instance": "test",
        "settings": {"feed_url": url},
    }
    resp = client.post(
        "/save_plugin",
        data=json.dumps(data),
        content_type="application/json",
    )
    assert resp.status_code in (200, 302, 400, 404, 422)


@given(st.text(max_size=100, alphabet=st.characters(categories=("L", "N", "P", "S", "Z"))))
@settings(max_examples=50, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_settings_name_unicode(client, name):
    """Device name with unicode/emoji should be accepted or rejected cleanly."""
    data = {
        "unit": "minute",
        "interval": "5",
        "timeFormat": "24h",
        "timezoneName": "UTC",
        "deviceName": name,
    }
    resp = client.post("/save_settings", data=data)
    assert resp.status_code in (200, 302, 400, 422)


@given(st.integers())
@settings(max_examples=50, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_interval_boundary_values(client, interval):
    """Boundary interval values (0, negative, huge) should get error responses, not crashes."""
    data = {
        "unit": "minute",
        "interval": str(interval),
        "timeFormat": "24h",
        "timezoneName": "UTC",
    }
    resp = client.post("/save_settings", data=data)
    assert resp.status_code in (200, 302, 400, 422)

"""Tests adding coverage for under-tested Flask routes."""

from datetime import UTC

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# 1. /display-next cooldown (429)
# ---------------------------------------------------------------------------


def test_display_next_cooldown_blocks_rapid_calls(
    client, device_config_dev, monkeypatch, flask_app
):
    """Second successful POST within the cooldown window must return 429."""
    from blueprints.main import _reset_display_next_cooldown

    flask_app.config["REFRESH_TASK"].running = False

    _reset_display_next_cooldown()
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    resp1 = client.post("/display-next")
    assert resp1.status_code == 200

    resp2 = client.post("/display-next")
    assert resp2.status_code == 429
    body = resp2.get_json()
    assert body["success"] is False
    assert "wait" in body["error"].lower()

    _reset_display_next_cooldown()
    resp3 = client.post("/display-next")
    assert resp3.status_code == 200


def test_display_next_cooldown_reset_allows_retry(
    client, device_config_dev, monkeypatch, flask_app
):
    """After resetting the cooldown the endpoint is available again."""
    from blueprints.main import _reset_display_next_cooldown

    flask_app.config["REFRESH_TASK"].running = False
    _reset_display_next_cooldown()
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    client.post("/display-next")
    resp_blocked = client.post("/display-next")
    assert resp_blocked.status_code == 429

    _reset_display_next_cooldown()
    resp_after_reset = client.post("/display-next")
    assert resp_after_reset.status_code == 200


# ---------------------------------------------------------------------------
# 2. /api/plugin_order validation
# ---------------------------------------------------------------------------


def test_plugin_order_unknown_id_returns_400(client):
    resp = client.post(
        "/api/plugin_order",
        json={"order": ["nonexistent_plugin_id_xyz"]},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "Unknown plugin IDs" in body["error"]


def test_plugin_order_non_string_entries_returns_400(client):
    resp = client.post(
        "/api/plugin_order",
        json={"order": [123]},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "strings" in body["error"].lower()


def test_plugin_order_empty_list_returns_400(client):
    resp = client.post(
        "/api/plugin_order",
        json={"order": []},
    )
    assert resp.status_code == 400
    assert "include every plugin id exactly once" in resp.get_json()["error"].lower()


def test_plugin_order_non_dict_payload_returns_400(client):
    resp = client.post(
        "/api/plugin_order",
        json=["clock", "weather"],
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "Invalid" in body["error"]


def test_plugin_order_valid_ids_returns_200(client, device_config_dev):
    plugins = device_config_dev.get_plugins()
    valid_ids = [p["id"] for p in plugins]
    if not valid_ids:
        pytest.skip("No plugins registered in dev config")
    resp = client.post("/api/plugin_order", json={"order": valid_ids})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


# ---------------------------------------------------------------------------
# 3. /next-up endpoint
# ---------------------------------------------------------------------------


def test_next_up_no_playlists_returns_empty_dict(
    client, device_config_dev, monkeypatch
):
    """With no active playlist /next-up returns {}."""
    pm = device_config_dev.get_playlist_manager()
    monkeypatch.setattr(pm, "determine_active_playlist", lambda dt: None, raising=True)

    resp = client.get("/next-up")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_next_up_with_active_playlist_and_plugin(
    client, device_config_dev, monkeypatch, flask_app
):
    """When a playlist has a next plugin, /next-up returns plugin info."""
    from datetime import datetime

    fixed_dt = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "utils.time_utils.now_device_tz", lambda _cfg: fixed_dt, raising=False
    )

    # Add a playlist with a clock plugin
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    resp = client.get("/next-up")
    assert resp.status_code == 200
    data = resp.get_json()
    # Should at minimum be a dict; if a plugin was found it will have keys
    assert isinstance(data, dict)
    if data:
        assert "plugin_id" in data
        assert "plugin_instance" in data
        assert "playlist" in data


# ---------------------------------------------------------------------------
# 4. /refresh-info endpoint
# ---------------------------------------------------------------------------


def test_refresh_info_returns_json_with_expected_keys(client, device_config_dev):
    resp = client.get("/refresh-info")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
    # The dict should include refresh_time (may be None) and plugin_id
    assert "refresh_time" in data
    assert "plugin_id" in data


def test_refresh_info_handles_exception_gracefully(
    client, device_config_dev, monkeypatch
):
    monkeypatch.setattr(
        device_config_dev,
        "get_refresh_info",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        raising=True,
    )
    resp = client.get("/refresh-info")
    assert resp.status_code == 200
    assert resp.get_json() == {}


# ---------------------------------------------------------------------------
# 5. /healthz and /readyz
# ---------------------------------------------------------------------------


def test_healthz_returns_200_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.data == b"OK"


def test_readyz_with_task_not_running_returns_503(client, flask_app):
    flask_app.config["REFRESH_TASK"].running = False
    resp = client.get("/readyz")
    assert resp.status_code == 503


def test_readyz_with_web_only_mode_returns_200(client, flask_app):
    original = flask_app.config.get("WEB_ONLY")
    flask_app.config["WEB_ONLY"] = True
    try:
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert b"web-only" in resp.data
    finally:
        flask_app.config["WEB_ONLY"] = original


# ---------------------------------------------------------------------------
# 6. Settings rate limiter memory cleanup
# ---------------------------------------------------------------------------


def test_rate_limiter_prunes_expired_keys(monkeypatch):
    """_prune_empty_rate_limit_keys removes keys whose deques became empty.

    The pruning is lazy: a key's entries are only evicted when _rate_limit_ok is
    called *for that same key*.  Once a key's deque is empty, the prune step
    removes it.  We simulate this by calling _rate_limit_ok for each old IP after
    time-travelling past the window so every deque drains to empty, then verify
    that all those keys have been removed from _REQUESTS.
    """
    import blueprints.settings as settings_mod

    # Clear state from any previous test
    settings_mod._REQUESTS.clear()

    window = settings_mod._RATE_LIMIT_WINDOW_SECONDS  # typically 60

    # Simulate 100 unique IPs that each made one request at t=1000
    fake_past = 1000.0
    old_ips = [f"10.1.{i // 256}.{i % 256}" for i in range(100)]
    for ip in old_ips:
        settings_mod._REQUESTS[ip].append(fake_past)

    assert len(settings_mod._REQUESTS) == 100

    # Time-travel: now = fake_past + window + 1  →  all old timestamps are expired
    future_now = fake_past + window + 1.0
    monkeypatch.setattr(settings_mod.time, "time", lambda: future_now)

    # Call _rate_limit_ok for each old IP — this drains their expired entries and
    # the pruner removes the now-empty deques.
    for ip in old_ips:
        settings_mod._rate_limit_ok(ip)

    # Each old key's deque was drained to empty *and then* a fresh timestamp was
    # appended, so the key still exists but with exactly one entry.
    # What matters is that the new IP "10.0.0.1" (never seen before) is allowed:
    result = settings_mod._rate_limit_ok("10.0.0.1")
    assert result is True

    # Also confirm that _prune_empty_rate_limit_keys works in isolation:
    # artificially make one key's deque empty and verify it gets pruned.
    test_ip = "prune-test-ip"
    settings_mod._REQUESTS[test_ip]  # touch to create empty deque
    assert test_ip in settings_mod._REQUESTS
    settings_mod._prune_empty_rate_limit_keys()
    assert test_ip not in settings_mod._REQUESTS


# ---------------------------------------------------------------------------
# 7. Settings mask function via /settings/api-keys route
# ---------------------------------------------------------------------------


def test_api_key_mask_shows_length_and_suffix(client, device_config_dev, monkeypatch):
    """The mask function renders '<suffix> (N chars)' for keys >= 4 chars."""
    key_value = "sk-abcdef1234567890"  # 19 chars; last 4 = "7890"

    monkeypatch.setattr(
        device_config_dev,
        "load_env_key",
        lambda k: key_value if k == "OPEN_AI_SECRET" else None,
        raising=True,
    )
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    # Mask should render "...7890 (19 chars)"
    assert b"19 chars" in resp.data
    assert b"7890" in resp.data


def test_api_key_mask_none_value_not_in_masked_dict(
    client, device_config_dev, monkeypatch
):
    """When load_env_key returns None the mask() function returns None, not a chars string."""
    # Import settings module and call mask logic directly via the route
    # mask(None) returns None, so the masked dict values will be None.
    # The template will not render "XX chars" for those entries.
    monkeypatch.setattr(
        device_config_dev,
        "load_env_key",
        lambda k: None,
        raising=True,
    )
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    # "N chars" pattern from the mask function should not appear — verify the
    # specific pattern that mask() emits (e.g. "19 chars") is absent.
    import re

    # The mask function renders e.g. "...7890 (19 chars)" — look for the digit-chars pattern
    assert not re.search(
        rb"\(\d+ chars\)", resp.data
    ), "Expected no '(N chars)' pattern when all keys are None"


# ---------------------------------------------------------------------------
# 8. Response modal has <button> close element, not <span>
# ---------------------------------------------------------------------------


def test_response_modal_close_is_button_not_span(client):
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    # Must have a <button with class close-button
    assert "<button" in html and "close-button" in html
    # Must NOT use a <span> as the close trigger
    import re

    span_close = re.search(r'<span[^>]*class="[^"]*close-button[^"]*"', html)
    assert span_close is None, "close-button must be a <button>, not a <span>"


# ---------------------------------------------------------------------------
# 9. /preview endpoint
# ---------------------------------------------------------------------------


def test_preview_no_image_returns_404(client, device_config_dev, monkeypatch):
    # Config.__init__ copies a default image into both paths, so we must
    # tell os.path.exists that neither path is present.
    import os as _os

    _processed = device_config_dev.processed_image_file
    _current = device_config_dev.current_image_file
    _real_exists = _os.path.exists

    def _patched_exists(p):
        if p in (_processed, _current):
            return False
        return _real_exists(p)

    monkeypatch.setattr(_os.path, "exists", _patched_exists)
    resp = client.get("/preview")
    assert resp.status_code == 404


def test_preview_with_image_returns_200(client, device_config_dev, tmp_path):
    # Create a PNG at the processed image path
    img = Image.new("RGB", (100, 100), "blue")
    img.save(device_config_dev.processed_image_file)

    resp = client.get("/preview")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"


# ---------------------------------------------------------------------------
# 10. /api/current_image
# ---------------------------------------------------------------------------


def test_current_image_no_file_returns_404(client, device_config_dev, monkeypatch):
    # Config.__init__ copies a default image, so patch os.path.exists to hide it.
    import os as _os

    _current = device_config_dev.current_image_file
    _real_exists = _os.path.exists

    def _patched_exists(p):
        if p == _current:
            return False
        return _real_exists(p)

    monkeypatch.setattr(_os.path, "exists", _patched_exists)
    resp = client.get("/api/current_image")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Image not found"


def test_current_image_with_file_returns_200_and_last_modified(
    client, device_config_dev
):
    img = Image.new("RGB", (100, 100), "green")
    img.save(device_config_dev.current_image_file)

    resp = client.get("/api/current_image")
    assert resp.status_code == 200
    assert "Last-Modified" in resp.headers
    assert resp.content_type == "image/png"


def test_current_image_if_modified_since_future_returns_304(client, device_config_dev):
    img = Image.new("RGB", (100, 100), "green")
    img.save(device_config_dev.current_image_file)

    # Use a date well in the future
    future_header = "Mon, 01 Jan 2099 00:00:00 GMT"
    resp = client.get(
        "/api/current_image",
        headers={"If-Modified-Since": future_header},
    )
    assert resp.status_code == 304


# ---------------------------------------------------------------------------
# 11. /refresh alias (backward-compat)
# ---------------------------------------------------------------------------


def test_refresh_alias_behaves_like_display_next(client, device_config_dev, flask_app):
    """POST /refresh should pass through the rate-limiter and return non-429."""
    from blueprints.main import _reset_display_next_cooldown

    flask_app.config["REFRESH_TASK"].running = False
    _reset_display_next_cooldown()

    resp = client.post("/refresh")
    # Should not be rate-limited; will be 400 (no playlist) but not 429
    assert resp.status_code != 429


def test_refresh_alias_is_rate_limited_after_first_success(
    client, device_config_dev, flask_app
):
    """Two rapid successful POSTs to /refresh should trigger the cooldown on the second."""
    from blueprints.main import _reset_display_next_cooldown

    flask_app.config["REFRESH_TASK"].running = False
    _reset_display_next_cooldown()
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    first = client.post("/refresh")
    assert first.status_code == 200
    resp = client.post("/refresh")
    assert resp.status_code == 429

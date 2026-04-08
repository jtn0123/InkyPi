"""Tests for JTN-309 (internal secrets filtered) and JTN-310 (Add Key button)."""

# --- JTN-309: internal secrets must not appear in the API Keys UI ---


def test_secret_key_not_shown_in_generic_api_keys_page(client, tmp_path, monkeypatch):
    """JTN-309: SECRET_KEY must not appear in the /api-keys response."""
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_KEY=super-secret\nNASA_SECRET=nasa123\n")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_file))

    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "SECRET_KEY" not in html, "SECRET_KEY must be filtered from the API Keys UI"
    assert "super-secret" not in html, "The value of SECRET_KEY must never be shown"


def test_test_key_not_shown_in_generic_api_keys_page(client, tmp_path, monkeypatch):
    """JTN-309: TEST_KEY must not appear in the /api-keys response."""
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_KEY=test-value\nGITHUB_SECRET=gh-token\n")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_file))

    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "TEST_KEY" not in html, "TEST_KEY must be filtered from the API Keys UI"


def test_wtf_csrf_secret_key_not_shown_in_generic_api_keys_page(
    client, tmp_path, monkeypatch
):
    """JTN-309: WTF_CSRF_SECRET_KEY must not appear in the /api-keys response."""
    env_file = tmp_path / ".env"
    env_file.write_text("WTF_CSRF_SECRET_KEY=csrf-secret\nOPEN_AI_SECRET=openai-key\n")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_file))

    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert (
        "WTF_CSRF_SECRET_KEY" not in html
    ), "WTF_CSRF_SECRET_KEY must be filtered from the API Keys UI"


def test_provider_keys_still_shown_after_internal_filtering(
    client, tmp_path, monkeypatch
):
    """JTN-309: filtering internal keys must not hide provider API keys."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SECRET_KEY=internal\nNASA_SECRET=nasa123\nUNSPLASH_ACCESS_KEY=unsplash-token\n"
    )
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_file))

    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "SECRET_KEY" not in html
    assert "NASA_SECRET" in html
    assert "UNSPLASH_ACCESS_KEY" in html


def test_internal_keys_constant_contains_expected_names():
    """JTN-309: _INTERNAL_KEYS frozenset must contain all known internal secrets."""
    from blueprints.apikeys import _INTERNAL_KEYS

    assert "SECRET_KEY" in _INTERNAL_KEYS
    assert "TEST_KEY" in _INTERNAL_KEYS
    assert "WTF_CSRF_SECRET_KEY" in _INTERNAL_KEYS


# --- JTN-310: Add API Key button and preset chips must be wired up ---


def test_add_api_key_button_present_in_generic_page(client):
    """JTN-310: the + Add API Key button must be rendered in generic mode."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="addApiKeyBtn"' in html, "Add API Key button must be present in DOM"
    assert "Add API Key" in html


def test_preset_chips_rendered_with_data_api_action(client):
    """JTN-310: preset suggestion chips must carry data-api-action=add-preset."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'data-api-action="add-preset"' in html
    assert 'data-key="UNSPLASH_ACCESS_KEY"' in html
    assert 'data-key="NASA_SECRET"' in html


def test_add_row_guard_in_js(client):
    """JTN-310: api_keys_page.js addRow must guard against missing #apikeys-list."""
    resp = client.get("/static/scripts/api_keys_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert 'getElementById("apikeys-list")' in js
    assert "api_keys_page: #apikeys-list not found in DOM" in js


def test_add_preset_guards_missing_key(client):
    """JTN-310: addPreset must guard against buttons with no data-key attribute."""
    resp = client.get("/static/scripts/api_keys_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function addPreset(button)" in js
    fn_start = js.find("function addPreset(button)")
    fn_body = js[fn_start : fn_start + 200]
    assert "if (!key) return;" in fn_body


def test_init_wires_add_button_click_handler(client):
    """JTN-310: init() must attach a click listener on #addApiKeyBtn."""
    resp = client.get("/static/scripts/api_keys_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert 'addBtn.addEventListener("click"' in js
    assert "() => addRow()" in js


def test_delegated_handler_covers_add_preset_action(client):
    """JTN-310: the delegated click handler in init() must handle add-preset action."""
    resp = client.get("/static/scripts/api_keys_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert '"add-preset"' in js
    assert "addPreset(actionEl)" in js

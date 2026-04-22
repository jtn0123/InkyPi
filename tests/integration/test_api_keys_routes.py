import importlib.util
from pathlib import Path


def test_api_keys_page_loads(client):
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-page-shell="management"' in body
    assert 'id="saveApiKeysBtn"' in body
    assert "Save API keys" in body
    assert "Third-party credentials used by plugins." in body
    # The managed API keys page renders a `6 providers` status chip below
    # the header (see test_managed_api_keys_renders_all_six_providers).


def test_api_keys_page_shows_configured_count(client, device_config_dev):
    device_config_dev.set_env_key("NASA_SECRET", "nasa-test-key")
    device_config_dev.set_env_key("OPEN_AI_SECRET", "openai-test-key")

    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert body.count('data-role="key-chip">Configured</span>') == 2


def test_save_api_keys_and_read_back(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    # Save a key
    resp = client.post(
        "/settings/save_api_keys", data={"NASA_SECRET": "route-test-123"}
    )
    assert resp.status_code == 200
    # Read back via config API
    # Dynamically import config.py
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec
    assert spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    assert cfg.load_env_key("NASA_SECRET") == "route-test-123"


def test_save_api_keys_empty_value_preserves_existing(client, monkeypatch, tmp_path):
    """JTN-598: an empty posted value must not overwrite the existing .env entry."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec
    assert spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    cfg.set_env_key("OPEN_AI_SECRET", "real-openai-key-abc123")

    resp = client.post(
        "/settings/save_api_keys",
        data={"OPEN_AI_SECRET": "", "NASA_SECRET": ""},
    )
    assert resp.status_code == 200
    # Real key must still be intact — empty value means "leave unchanged".
    assert cfg.load_env_key("OPEN_AI_SECRET") == "real-openai-key-abc123"
    assert "OPEN_AI_SECRET" not in resp.get_json()["updated"]


def test_save_api_keys_bullet_placeholder_preserves_existing(
    client, monkeypatch, tmp_path
):
    """JTN-598: a value of pure U+2022 characters (the legacy placeholder) must
    not overwrite the existing key — even from a stale cached page."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec
    assert spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    cfg.set_env_key("OPEN_AI_SECRET", "real-openai-key-abc123")

    bullet_placeholder = "\u2022" * 32
    resp = client.post(
        "/settings/save_api_keys",
        data={"OPEN_AI_SECRET": bullet_placeholder},
    )
    assert resp.status_code == 200
    # Real key must still be intact — bullet placeholder must be rejected.
    assert cfg.load_env_key("OPEN_AI_SECRET") == "real-openai-key-abc123"
    body = resp.get_json()
    assert "OPEN_AI_SECRET" not in body["updated"]
    assert body.get("skipped_placeholder") == ["OPEN_AI_SECRET"]


def test_api_keys_page_does_not_prefill_bullets_in_value_attribute(
    client, device_config_dev
):
    """JTN-598: the server-rendered page must not include literal U+2022 chars
    in any <input value=...>. Pre-filling with bullets is the root cause of the
    data-destruction bug."""
    device_config_dev.set_env_key("OPEN_AI_SECRET", "test-key-for-prefill-check")
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # No literal U+2022 chars should appear inside any value="..." attribute.
    # (They may appear elsewhere on the page — e.g., status line text — that's
    # fine; the bug is specifically about input value attributes being
    # editable form data.)
    import re

    for match in re.finditer(r'value="([^"]*)"', body):
        assert "\u2022" not in match.group(1), (
            f"Found U+2022 bullet chars in a value= attribute: {match.group(1)!r}. "
            "This is the JTN-598 data-destruction regression."
        )


def test_api_keys_page_configured_fields_have_leave_blank_placeholder(
    client, device_config_dev
):
    """JTN-598: a configured provider's input should render with a placeholder
    telling the user that leaving it blank keeps the existing key — instead of
    the generic 'Enter <provider> API key' placeholder used for unconfigured."""
    device_config_dev.set_env_key("NASA_SECRET", "nasa-test-key")
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    import re

    nasa_input = re.search(r'<input[^>]*id="nasa-input"[^>]*>', body)
    assert nasa_input is not None, "NASA input must be rendered"
    assert "leave blank to keep current" in nasa_input.group(0).lower()
    unsplash_input = re.search(r'<input[^>]*id="unsplash-input"[^>]*>', body)
    assert unsplash_input is not None, "Unsplash input must be rendered"
    assert "enter unsplash" in unsplash_input.group(0).lower()


def test_save_api_keys_whitespace_padded_bullets_are_rejected(
    client, monkeypatch, tmp_path
):
    """JTN-598 (CodeRabbit follow-up): the bullet-placeholder rejection must
    also catch values where leading/trailing whitespace has been added by a
    client (e.g. '  ••••  '). Otherwise a stale page could send a whitespace-
    padded bullet string and bypass the defense-in-depth check."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec
    assert spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    cfg.set_env_key("OPEN_AI_SECRET", "real-key-should-not-be-clobbered")

    resp = client.post(
        "/settings/save_api_keys",
        data={"OPEN_AI_SECRET": "  " + "\u2022" * 16 + "  "},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "OPEN_AI_SECRET" not in body["updated"]
    assert body["skipped_placeholder"] == ["OPEN_AI_SECRET"]
    assert cfg.load_env_key("OPEN_AI_SECRET") == "real-key-should-not-be-clobbered"


def test_save_api_keys_whitespace_only_is_treated_as_unchanged(
    client, monkeypatch, tmp_path
):
    """JTN-598 (CodeRabbit follow-up): a whitespace-only submission must be
    treated the same as empty (leave current key unchanged), not saved as a
    whitespace string."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec
    assert spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    cfg.set_env_key("OPEN_AI_SECRET", "real-key-preserved")

    resp = client.post(
        "/settings/save_api_keys",
        data={"OPEN_AI_SECRET": "   \t  "},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "OPEN_AI_SECRET" not in body["updated"]
    # Whitespace-only is "empty/unchanged", not "rejected as placeholder".
    assert "skipped_placeholder" not in body
    assert cfg.load_env_key("OPEN_AI_SECRET") == "real-key-preserved"


def test_save_api_keys_mixed_bullet_and_real_chars_is_accepted(
    client, monkeypatch, tmp_path
):
    """JTN-598: the rejection rule only fires when the value is **solely** U+2022
    characters. A value like 'abc•••' is a legitimate (if oddly-chosen) password
    and must be saved normally — we must not silently drop real keys that
    happen to contain bullet chars."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec
    assert spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()

    mixed_value = "abc" + "\u2022" * 3  # "abc•••"
    resp = client.post(
        "/settings/save_api_keys",
        data={"OPEN_AI_SECRET": mixed_value},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "OPEN_AI_SECRET" in body["updated"]
    assert "skipped_placeholder" not in body
    assert cfg.load_env_key("OPEN_AI_SECRET") == mixed_value


def test_save_api_keys_normal_response_omits_skipped_placeholder_field(
    client, monkeypatch, tmp_path
):
    """JTN-598: the new `skipped_placeholder` field should only appear in the
    response when at least one value was actually skipped. A clean save should
    have the same response shape as before the fix (forward compatibility)."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    resp = client.post(
        "/settings/save_api_keys",
        data={"NASA_SECRET": "real-normal-key"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert "NASA_SECRET" in body["updated"]
    assert "skipped_placeholder" not in body


def test_save_api_keys_partial_placeholder_reject(client, monkeypatch, tmp_path):
    """JTN-598: posting a mix of real + bullet values should save the real ones
    and skip the bullet ones, and the response must name the skipped keys."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec
    assert spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    cfg.set_env_key("OPEN_AI_SECRET", "preexisting-openai-key")

    resp = client.post(
        "/settings/save_api_keys",
        data={
            "OPEN_AI_SECRET": "\u2022" * 32,  # bullet placeholder → rejected
            "NASA_SECRET": "new-nasa-real-key",  # real → saved
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["updated"] == ["NASA_SECRET"]
    assert body["skipped_placeholder"] == ["OPEN_AI_SECRET"]
    # Critical assertion: the real existing OpenAI key must still be intact.
    assert cfg.load_env_key("OPEN_AI_SECRET") == "preexisting-openai-key"
    assert cfg.load_env_key("NASA_SECRET") == "new-nasa-real-key"


def test_api_keys_js_no_longer_references_mask_placeholder():
    """JTN-598: after the fix, api_keys_page.js should no longer reference
    `maskPlaceholder` anywhere — the constant was removed and the function that
    used it (`updateConfiguredStatus`) should clear the field instead of
    re-filling it with bullets. Static check against accidental re-introduction."""
    js_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "api_keys_page.js"
    )
    content = js_path.read_text(encoding="utf-8")
    assert "maskPlaceholder" not in content, (
        "api_keys_page.js must not reference `maskPlaceholder` after JTN-598. "
        "The bullet-character placeholder was the root cause of the data-"
        "destruction bug — any re-introduction would re-open the hole."
    )
    assert "\u2022\u2022\u2022\u2022" not in content, (
        "api_keys_page.js must not contain a bullet-character placeholder "
        "sequence. See JTN-598."
    )


def test_api_keys_template_no_longer_references_bullet_placeholder():
    """JTN-598: the api_keys.html template and api_key_card.html macro must
    not contain the literal bullet sequence. Static check against regression."""
    template_path = (
        Path(__file__).resolve().parents[2] / "src" / "templates" / "api_keys.html"
    )
    macro_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "templates"
        / "macros"
        / "api_key_card.html"
    )
    for path in (template_path, macro_path):
        content = path.read_text(encoding="utf-8")
        assert "\u2022\u2022\u2022\u2022" not in content, (
            f"{path.name} must not contain a bullet-character placeholder "
            "sequence. See JTN-598 — pre-filling value= with bullets causes "
            "data destruction."
        )
    # Macro must still render the input, just with an empty value.
    macro_content = macro_path.read_text(encoding="utf-8")
    assert 'value=""' in macro_content, (
        "api_key_card.html macro must render inputs with an empty value= so "
        "the user can cleanly type a new key without appending to a placeholder."
    )


def test_api_keys_responsive_css_reserves_short_viewport_sticky_rule_for_settings():
    """JTN-599: API keys no longer uses a bottom sticky save bar.

    The short-viewport sticky treatment is now intentionally reserved for
    /settings, while /settings/api-keys moved its save action into the header.
    Keep the shared media query, but prevent the old API-key selector from
    creeping back in."""
    css_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "styles"
        / "partials"
        / "_responsive-large.css"
    )
    content = css_path.read_text(encoding="utf-8")
    # Must keep the max-height: 860px media query for /settings.
    assert "max-height: 860px" in content, (
        "JTN-599: _responsive-large.css must define a @media (max-height: 860px) "
        "rule to pin the Settings save button on short laptop screens."
    )
    assert ".settings-panel .buttons-container" in content
    assert ".api-keys-frame .buttons-container" not in content


def test_delete_api_key(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    # Prime .env
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec
    assert spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    cfg.set_env_key("NASA_SECRET", "to-delete")

    # Delete via route
    resp = client.post("/settings/delete_api_key", data={"key": "NASA_SECRET"})
    assert resp.status_code == 200

    # Ensure removed
    assert cfg.load_env_key("NASA_SECRET") is None

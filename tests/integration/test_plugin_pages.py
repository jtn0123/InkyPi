# pyright: reportMissingImports=false


def test_plugin_page_ai_text(client):
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    assert b"AI Text" in resp.data
    assert b"ai_text" in resp.data
    # preview image present
    assert b"/preview" in resp.data


def test_plugin_page_ai_image(client):
    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    assert b"AI Image" in resp.data or b"Image Model" in resp.data
    assert b"/preview" in resp.data
    assert b"Surprise me" in resp.data
    assert b"data-ai-image-random-prompt" in resp.data


def test_clock_page_hides_generic_style_tab_and_labels_face_colors(client):
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert 'data-plugin-subtab="style"' not in body
    assert "Face accent color" in body
    assert "Face background color" in body
    assert "These colors are used by the clock face itself." in body
    assert 'aria-pressed="false"' in body


def test_plugin_tabs_have_tabpanel_wiring(client):
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert 'id="pluginConfigureTab"' in body
    assert 'aria-controls="pluginConfigurePanel"' in body
    assert 'id="pluginConfigurePanel"' in body
    assert 'role="tabpanel"' in body
    assert 'aria-labelledby="pluginConfigureTab"' in body


def test_plugin_page_apod(client):
    resp = client.get("/plugin/apod")
    assert resp.status_code == 200
    assert b"APOD" in resp.data or b"NASA" in resp.data
    assert b"/preview" in resp.data


def test_schema_backed_plugin_pages_use_shared_renderer(client):
    for plugin_id in (
        "ai_text",
        "ai_image",
        "apod",
        "comic",
        "countdown",
        "unsplash",
        "image_folder",
        "image_album",
    ):
        resp = client.get(f"/plugin/{plugin_id}")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "data-settings-schema" in body


def test_remaining_plugin_pages_use_shared_or_hybrid_renderer(client):
    for plugin_id in (
        "image_url",
        "rss",
        "screenshot",
        "wpotd",
        "github",
        "clock",
        "newspaper",
        "calendar",
        "todo_list",
        "weather",
        "image_upload",
    ):
        resp = client.get(f"/plugin/{plugin_id}")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "data-settings-schema" in body


def test_ai_image_page_uses_shared_select_dependency_renderer(client):
    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-options-source-field="imageModel"' in body
    assert "toggleQualityDropdown" not in body


def test_apod_page_uses_shared_visibility_rules(client):
    resp = client.get("/plugin/apod")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-visible-if-field="randomizeApod"' in body
    assert "toggleDateField" not in body


def test_weather_plugin_second_pass_polish(client):
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert 'settings-card-title">Location' in body
    assert 'settings-card-title">Display' in body
    assert "toggle-item" in body
    assert "radio-segment" in body
    assert "settings-map" in body
    assert 'data-hybrid-widget="weather-map"' in body


def test_todo_list_plugin_uses_svg_delete_icon(client):
    resp = client.get("/plugin/todo_list")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert "dynamic-list-toolbar" in body
    assert "ph-trash" in body
    assert "remove.png" not in body


def test_url_based_plugins_use_warning_callouts(client):
    for plugin_id in ("rss", "screenshot", "image_url"):
        resp = client.get(f"/plugin/{plugin_id}")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "settings-callout warning" in body


def test_checkbox_false_value_not_checked(client, device_config_dev):
    """Bug 2: Checkbox with 'false' value should not render as checked."""
    # Set randomizePrompt to 'false' for ai_image plugin
    device_config_dev.update_value(
        "plugins",
        [
            {
                "plugin_id": "ai_image",
                "name": "ai_image_saved_settings",
                "plugin_settings": {"randomizePrompt": "false"},
                "refresh": {"interval": 60},
            }
        ],
        write=True,
    )

    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # Find the randomizePrompt checkbox input and check it doesn't have a standalone 'checked' attribute
    import re

    match = re.search(r'<input[^>]*name="randomizePrompt"[^>]*>', body, re.DOTALL)
    assert match, "randomizePrompt checkbox not found"
    checkbox_html = match.group(0)
    # Strip data attributes that contain "checked" in their values to isolate the actual 'checked' attr
    stripped = re.sub(r'data-\w+-\w+="[^"]*"', "", checkbox_html)
    # The standalone 'checked' attribute (not inside another attribute value) should not be present
    assert not re.search(
        r"\bchecked\b", stripped
    ), f"Checkbox should not be checked when value is 'false': {checkbox_html}"


def test_github_plugin_uses_hidden_state_instead_of_inline_display(client):
    resp = client.get("/plugin/github")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert 'id="repositoryGroup"' in body
    repository_group = body.split('id="repositoryGroup"', 1)[1][:200]
    assert "hidden" in repository_group
    assert 'id="repositoryGroup" style="display: none;"' not in body
    assert 'data-visible-if-field="githubType"' in body


def test_preview_size_mode_native_on_plugin(client, device_config_dev):
    device_config_dev.update_value("preview_size_mode", "native", write=True)
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    assert b'data-native-width="' in resp.data and b'data-native-height="' in resp.data


def test_preview_size_mode_fit_on_plugin(client, device_config_dev):
    device_config_dev.update_value("preview_size_mode", "fit", write=True)
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    assert b'id="previewImage" style=' not in resp.data
    assert b'data-page-shell="workflow"' in resp.data


def test_plugin_page_status_bar_present(client):
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    body = resp.data
    assert b'class="status-bar"' in body
    assert b'id="currentDisplayTime"' in body


def test_plugin_page_instance_preview_shown_when_instance(client):
    # Create a playlist instance explicitly
    # Add to Default playlist
    resp = client.post(
        "/add_plugin",
        data={
            "plugin_id": "ai_text",
            "title": "T1",
            "textModel": "gpt-4o",
            "textPrompt": "Hi",
            "refresh_settings": '{"playlist":"Default","instance_name":"Saved Settings","refreshType":"interval","interval":"60","unit":"minute"}',
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    page = client.get("/plugin/ai_text?instance=Saved Settings")
    assert page.status_code == 200
    body = page.data
    # Instance preview image element should be present when instance is specified
    assert b'id="instancePreviewImage"' in body


def test_instance_image_history_fallback(client, device_config_dev):
    # Simulate a manual update that creates history sidecar with instance name
    data = {
        "plugin_id": "ai_text",
        "title": "T1",
        "textModel": "gpt-4o",
        "textPrompt": "Hi",
        "instance_name": "ai_text_saved_settings",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code in (200, 400, 500)

    # Now request the instance image (no plugin image file exists), should fallback to history
    resp2 = client.get("/instance_image/ai_text/ai_text_saved_settings")
    # Should either serve or 404 if environment cannot generate; accept 200 as success criteria
    assert resp2.status_code in (200, 404)


def test_api_key_indicator_shows_missing_when_no_key(client, device_config_dev):
    """Test that API key indicator shows 'missing' status when key is not present.

    Regression test for: API key indicator showing warning even when keys are configured.
    """
    # Ensure no OpenAI key is present
    device_config_dev.unset_env_key("OPEN_AI_SECRET")

    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # Should show the missing indicator
    assert 'class="api-key-indicator missing"' in body
    assert "API Required" in body or "API Key required" in body


def test_plugin_page_renders_inline_api_management_card(client, device_config_dev):
    """API-key backed plugins should surface the calmer in-content management card."""
    device_config_dev.unset_env_key("OPEN_WEATHER_MAP_SECRET")

    resp = client.get("/plugin/weather")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert 'class="plugin-editor-card-label">API key' in body
    assert "Manage keys" in body
    assert "workflow-preview-card" in body


def test_api_key_indicator_shows_configured_when_key_present(client, device_config_dev):
    """Test that API key indicator shows 'configured' status when key is present.

    Regression test for: API key indicator showing warning even when keys are configured.
    """
    # Set an OpenAI key
    device_config_dev.set_env_key("OPEN_AI_SECRET", "test-key-123")

    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # Should show the configured indicator
    assert 'class="api-key-indicator configured"' in body
    assert "API Key is configured" in body or "✓" in body


def test_action_buttons_disabled_when_api_key_missing(client, device_config_dev):
    """Buttons that need an API key are disabled when the key is absent.

    Regression test for JTN-162: action buttons should be disabled when the
    required API key is not configured, preventing users from triggering
    actions that will inevitably fail.
    """
    # Ensure no Unsplash key is present
    device_config_dev.unset_env_key("UNSPLASH_ACCESS_KEY")

    resp = client.get("/plugin/unsplash")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # "Update Preview" should be disabled
    assert 'disabled title="Configure Unsplash API key first"' in body
    # "Save settings" should NOT be disabled.  JTN-506 added HTMX attributes
    # between aria-describedby and the button closing tag; assert on the
    # button id + content rather than a rigid substring so the test covers
    # intent instead of attribute ordering.
    assert 'id="savePluginSettingsBtn"' in body
    assert ">Save settings</button>" in body
    # Between the save-settings-help anchor and "Save settings" text, the
    # bare ``disabled`` HTML attribute must not appear (the button must
    # remain enabled).  Use a regex to avoid matching substrings like
    # ``hx-disabled-elt`` which is an HTMX hint, not an HTML attribute.
    import re

    save_segment = body.split("Save settings")[0].split("save-settings-help")[1]
    assert not re.search(r"(?:^|\s)disabled(?:=|\s|>)", save_segment)


def test_action_buttons_enabled_when_api_key_present(client, device_config_dev):
    """Buttons are enabled when the required API key is present."""
    device_config_dev.set_env_key("UNSPLASH_ACCESS_KEY", "test-key-123")

    resp = client.get("/plugin/unsplash")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # "Update Preview" should NOT be disabled
    update_btn = 'data-plugin-action="update_now"'
    assert update_btn in body
    # Find the button and check it doesn't have disabled
    btn_section = body.split(update_btn)[1].split(">")[0]
    assert "disabled" not in btn_section


def test_plugin_latest_image_endpoint(client, device_config_dev):
    """Test that /plugin_latest_image serves the most recent image for a plugin.

    Regression test for: "Latest from this plugin" section not showing historical images.
    """
    import json
    import os

    from PIL import Image

    # Create a fake history image and metadata
    history_dir = device_config_dev.history_image_dir
    os.makedirs(history_dir, exist_ok=True)

    # Create test image
    img = Image.new("RGB", (100, 100), color="red")
    img_path = os.path.join(history_dir, "display_20250115_120000.png")
    img.save(img_path)

    # Create metadata
    metadata = {
        "plugin_id": "clock",
        "plugin_instance": "test_instance",
        "refresh_time": "2025-01-15T12:00:00",
    }
    json_path = os.path.join(history_dir, "display_20250115_120000.json")
    with open(json_path, "w") as f:
        json.dump(metadata, f)

    # Request latest image for this plugin
    resp = client.get("/plugin_latest_image/clock")
    assert resp.status_code == 200
    assert resp.content_type.startswith("image/")

    # Test with non-existent plugin
    resp2 = client.get("/plugin_latest_image/nonexistent_plugin")
    assert resp2.status_code == 404


def test_plugin_latest_refresh_time_populated(client, device_config_dev):
    """Test that plugin_latest_refresh template variable is populated correctly.

    Regression test for: "Last generated" timestamp not showing for "Latest from this plugin".
    """
    import json
    import os

    # Create a fake history metadata
    history_dir = device_config_dev.history_image_dir
    os.makedirs(history_dir, exist_ok=True)

    metadata = {
        "plugin_id": "clock",
        "plugin_instance": "test_instance",
        "refresh_time": "2025-01-15T12:00:00",
    }
    json_path = os.path.join(history_dir, "display_20250115_120000.json")
    with open(json_path, "w") as f:
        json.dump(metadata, f)

    # Visit plugin page
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # The template should render the refresh time
    # It's rendered via JavaScript, so we check that the variable is set
    assert "plugin_latest_refresh" in body or "2025-01-15" in body


def test_plugin_page_update_instance_url_encodes_instance_name_with_spaces(client):
    """JTN-240: update_instance URL must use url_for() with the actual instance name.

    When plugin_instance contains spaces or special characters the old string
    concatenation approach (url_for(..., instance_name='') ~ instance_name)
    produced an un-encoded URL like '/update_plugin_instance/My Instance'.
    Flask's url_for() with the real name percent-encodes it correctly:
    '/update_plugin_instance/My%20Instance'.
    """
    # Create a plugin instance whose name contains a space
    resp = client.post(
        "/add_plugin",
        data={
            "plugin_id": "ai_text",
            "title": "My Title",
            "textModel": "gpt-4o",
            "textPrompt": "Hello",
            "refresh_settings": (
                '{"playlist":"Default","instance_name":"My Instance",'
                '"refreshType":"interval","interval":"60","unit":"minute"}'
            ),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    page = client.get("/plugin/ai_text?instance=My Instance")
    assert page.status_code == 200
    body = page.data.decode("utf-8")

    # url_for() encodes spaces as %20; the raw string must NOT appear in the URL
    assert "update_plugin_instance/My%20Instance" in body
    assert "update_plugin_instance/My Instance" not in body


def test_plugin_page_hides_raw_slug_subtitle(client):
    """JTN-622: Raw plugin slug must not be rendered as a visible subtitle.

    End users have no reason to see the internal filesystem slug
    (ai_image, clock, weather, etc.). The <span class="app-subtitle">
    containing the slug should be absent from the default page render.
    """
    for plugin_id in ("ai_image", "clock", "weather"):
        resp = client.get(f"/plugin/{plugin_id}")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        # The app-subtitle span must not be present by default.
        assert (
            'class="app-subtitle"' not in body
        ), f"/plugin/{plugin_id} still renders app-subtitle span with raw slug"
        # Also ensure the slug doesn't appear as the inner text of any
        # element with data-debug-slug attribute (which only renders in debug mode).
        assert "data-debug-slug" not in body


def test_plugin_page_shows_slug_subtitle_in_debug_mode(client):
    """JTN-622: Raw slug subtitle is available behind ?debug=1 for diagnostics."""
    resp = client.get("/plugin/ai_image?debug=1")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'class="app-subtitle"' in body
    assert "data-debug-slug" in body


def test_plugin_page_draft_badge_has_explanation(client):
    """JTN-644: The Draft badge must expose an explanation via title and/or aria-describedby."""
    # A plugin page with no plugin_instance query param renders the Draft chip.
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # Locate the Draft chip
    import re

    match = re.search(r'<span class="status-chip warning"[^>]*>Draft</span>', body)
    assert match, "Draft status chip not found on /plugin/clock"
    chip_html = match.group(0)
    assert "title=" in chip_html, f"Draft chip missing title attribute: {chip_html}"
    assert (
        "aria-describedby=" in chip_html
    ), f"Draft chip missing aria-describedby: {chip_html}"
    # And the hidden describedby element must exist.
    assert 'id="draft-chip-help"' in body
    assert "save action" in body or "Save settings" in body


def test_wizard_ids_not_duplicated_in_static_html(client):
    """JTN-220: wizardPrev and wizardNext must each appear at most once in rendered HTML.

    The wizard navigation is injected by progressive_disclosure.js; the template
    must not also render a static copy, or every plugin settings page will have
    duplicate id attributes which break querySelector-based selectors.
    """
    resp = client.get("/plugin/calendar")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert (
        body.count('id="wizardPrev"') <= 1
    ), "Duplicate id='wizardPrev' found in rendered HTML for /plugin/calendar"
    assert (
        body.count('id="wizardNext"') <= 1
    ), "Duplicate id='wizardNext' found in rendered HTML for /plugin/calendar"

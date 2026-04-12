"""JTN-648: Update Preview on plugin pages must route validation through the
app-level toast helpers, never the browser's native HTML5 tooltip.

Before this fix, clicking Update Preview (or pressing Enter) on the Image URL
or RSS Feed plugin with an empty required field showed the native browser
"Please fill out this field" bubble instead of the labelled app toast.

The fix has two pieces:

1. ``#settingsForm`` carries ``novalidate`` so the browser never surfaces its
   own validation bubble for any submit path.
2. ``plugin_page.js`` intercepts the ``settingsForm`` submit event AND the
   Update Preview click and routes both through
   ``FormValidator.validateAllInputsDetailed`` /
   ``FormValidator.buildValidationMessage`` /
   ``FormValidator.focusFirstInvalid`` — the same helpers JTN-378 wired up for
   Save Settings / Add to Playlist.
"""


def _get_plugin_page_js(client):
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_settings_form_has_novalidate(client):
    """The settings form must opt out of native HTML5 validation so no browser
    bubble can ever appear — all validation flows through the app-level
    helpers."""
    resp = client.get("/plugin/image_url")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Locate the settings form tag and confirm the novalidate attribute is
    # present on it. We look for the id so we don't match other forms on the
    # page.
    form_start = html.find('id="settingsForm"')
    assert form_start != -1, "#settingsForm must render on plugin pages"
    tag_close = html.find(">", form_start)
    assert tag_close != -1
    form_tag = html[form_start:tag_close]
    assert "novalidate" in form_tag, (
        "#settingsForm must carry the novalidate attribute so Update Preview "
        "and Enter-key submits never trigger native HTML5 tooltips (JTN-648)."
    )


def test_settings_form_has_novalidate_on_rss(client):
    """Same guarantee on the RSS Feed plugin — this is the other plugin cited
    in the JTN-648 dogfood report."""
    resp = client.get("/plugin/rss")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    form_start = html.find('id="settingsForm"')
    assert form_start != -1
    tag_close = html.find(">", form_start)
    form_tag = html[form_start:tag_close]
    assert "novalidate" in form_tag, (
        "#settingsForm must carry the novalidate attribute on the RSS Feed "
        "plugin page too (JTN-648)."
    )


def test_plugin_page_submit_handler_uses_detailed_validator(client):
    """Pressing Enter inside the settings form implicitly submits it. The
    submit handler must route the validation through the labelled helpers and
    surface a response modal, not rely on the browser's native bubble."""
    js = _get_plugin_page_js(client)

    # All three helpers from the JTN-378 pattern must be invoked on the submit
    # path so the experience mirrors Update Preview clicks.
    assert "validateAllInputsDetailed(settingsForm)" in js
    assert "buildValidationMessage(result)" in js
    assert "focusFirstInvalid(settingsForm)" in js

    # The JTN-648 marker must appear in the comments so future readers can
    # trace the intent.
    assert "JTN-648" in js


def test_plugin_page_update_preview_handler_still_uses_detailed_validator(client):
    """Regression guard for JTN-378: the click-driven Update Preview path must
    keep using the same helpers. This confirms JTN-648 did not regress the
    existing behaviour."""
    js = _get_plugin_page_js(client)

    # handleAction is the Update Preview / Update Instance / Add to Playlist
    # dispatcher.
    handle_idx = js.find("async function handleAction(")
    assert handle_idx != -1, "handleAction must exist in plugin_page.js"

    # Inside handleAction we expect the detailed validator + buildValidationMessage
    # + focusFirstInvalid for settingsForm (JTN-378 contract).
    handle_body = js[handle_idx : handle_idx + 2000]
    assert "validateAllInputsDetailed(settingsForm)" in handle_body
    assert "buildValidationMessage(result)" in handle_body
    assert "focusFirstInvalid(settingsForm)" in handle_body

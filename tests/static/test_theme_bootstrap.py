from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_HTML = ROOT / "src" / "templates" / "base.html"
PLUGIN_HTML = ROOT / "src" / "templates" / "plugin.html"
PLUGIN_SCHEMA_JS = ROOT / "src" / "static" / "scripts" / "plugin_schema.js"


def test_base_inlines_theme_and_tweaks_before_css() -> None:
    html = BASE_HTML.read_text(encoding="utf-8")

    inline_theme = html.index('localStorage.getItem("theme")')
    stylesheet = html.index('rel="stylesheet"')

    assert inline_theme < stylesheet
    assert "inkypi_tweaks_v1" in html
    assert 'root.setAttribute("data-aesthetic"' in html
    assert 'root.style.setProperty("--accent"' in html


def test_ai_image_prompt_tool_checks_selected_provider_key() -> None:
    js = PLUGIN_SCHEMA_JS.read_text(encoding="utf-8")
    html = PLUGIN_HTML.read_text(encoding="utf-8")

    assert "apiKeyServices" in html
    assert "window.__INKYPI_PLUGIN_BOOT__?.apiKeyServices" in js
    assert 'provider === "google" ? "Google AI" : "OpenAI"' in js
    assert "API Key not configured." in js

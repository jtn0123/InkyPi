"""Regression guard for the C1 settings-page script split."""

from pathlib import Path

SETTINGS_TEMPLATE = Path("src/templates/settings.html")


def test_settings_template_loads_feature_modules_before_bootstrap():
    html = SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    script_paths = [
        "scripts/settings/shared.js",
        "scripts/settings/form.js",
        "scripts/settings/modals.js",
        "scripts/settings/logs.js",
        "scripts/settings/diagnostics.js",
        "scripts/settings/navigation.js",
        "scripts/settings/actions.js",
        "scripts/settings_page.js",
    ]

    last_index = -1
    for script_path in script_paths:
        current_index = html.find(script_path)
        assert current_index != -1, f"{script_path} must be loaded by settings.html"
        assert current_index > last_index, (
            f"{script_path} must load after the previous settings script so the "
            "bootstrap sees every feature module"
        )
        last_index = current_index

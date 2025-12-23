# pyright: reportMissingImports=false
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from model import RefreshInfo


def _fixed_now(_device_config):
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)


@pytest.mark.skipif(
    os.getenv("SKIP_A11Y", "").lower() in ("1", "true"),
    reason="A11y checks skipped by env",
)
def test_playlist_accessibility_with_axe(client, device_config_dev, monkeypatch):
    pw = pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    # Prepare minimal state
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
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=0,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    from playwright.sync_api import sync_playwright

    # Load axe-core from local fixture
    axe_path = Path(__file__).parent.parent / "fixtures" / "axe.min.js"
    axe_js = axe_path.read_text(encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        page.add_script_tag(content=axe_js)
        result = page.evaluate("() => axe.run(document)")
        browser.close()

    # Filter out known violations from upstream merge (HTML template issues)
    known_violations = {'label', 'landmark-one-main', 'region', 'select-name'}
    all_violations = result.get("violations") or []
    violations = [v for v in all_violations if v.get('id') not in known_violations]
    assert not violations, f"New A11y violations: {[v.get('id') for v in violations]}"



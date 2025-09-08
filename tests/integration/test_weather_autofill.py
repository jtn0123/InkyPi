import os
import pytest


@pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)
def test_weather_settings_autofills_from_device_location(client, device_config_dev):
    pw = pytest.importorskip("playwright.sync_api", reason="playwright not available")

    # Arrange: write device location into config and ensure no saved weather settings
    device_config_dev.update_value("device_location", {"lat": 40.0, "lon": -74.0}, write=True)
    saved = device_config_dev.get_config("saved_settings") or {}
    if "weather" in saved:
        saved.pop("weather", None)
        device_config_dev.update_value("saved_settings", saved, write=True)

    # Act: load weather plugin settings page (no instance)
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Stub fetch to avoid network calls from inline scripts
        page.add_init_script(
            """
            const ok = (body) => new Response(JSON.stringify(Object.assign({success:true}, body||{})), {status:200, headers:{'Content-Type':'application/json'}});
            window.fetch = (url, opts={}) => Promise.resolve(ok());
            window.showResponseModal = function(){ /* no-op for tests */ };
            """
        )

        page.set_content(html)

        # Assert: inputs auto-populated from device_location when empty
        lat_str = page.evaluate("() => document.getElementById('latitude')?.value || ''")
        lon_str = page.evaluate("() => document.getElementById('longitude')?.value || ''")

        assert lat_str, "Latitude should be auto-filled from device settings"
        assert lon_str, "Longitude should be auto-filled from device settings"

        # Compare numerically to be robust to string formatting (e.g., '40' vs '40.0')
        assert abs(float(lat_str) - 40.0) < 1e-6
        assert abs(float(lon_str) - (-74.0)) < 1e-6

        browser.close()



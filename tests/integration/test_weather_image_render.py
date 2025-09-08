import json


def test_weather_template_loads_images(client, device_config_dev, monkeypatch):
    pw = __import__("pytest").importorskip(
        "playwright.sync_api", reason="playwright not available"
    )

    # Prepare a minimal weather response to drive template
    from plugins.weather.weather import Weather

    w = Weather({"id": "weather"})

    # Fake data to skip network
    def fake_get_weather_data(api_key, units, lat, lon):
        return {
            "timezone": "America/Los_Angeles",
            "current": {
                "dt": 1736298000,
                "temp": 79,
                "feels_like": 79,
                "weather": [{"icon": "01d"}],
                "sunrise": 1736262000,
                "sunset": 1736298000,
                "wind_speed": 4.6,
                "humidity": 51,
                "pressure": 1012,
                "uvi": 4,
                "visibility": 10000,
            },
            "daily": [
                {
                    "dt": 1736298000,
                    "temp": {"max": 80, "min": 65},
                    "weather": [{"icon": "01d"}],
                    "moon_phase": 0.5,
                }
            ]
            * 8,
            "hourly": [
                {"dt": 1736298000 + i * 3600, "temp": 70 + i % 5, "pop": 0, "rain": {}}
                for i in range(24)
            ],
        }

    def fake_get_air_quality(api_key, lat, lon):
        return {"list": [{"main": {"aqi": 1}}]}

    monkeypatch.setattr(w, "get_weather_data", fake_get_weather_data, raising=True)
    monkeypatch.setattr(w, "get_air_quality", fake_get_air_quality, raising=True)
    # Bypass API key requirement
    monkeypatch.setattr(
        device_config_dev, "load_env_key", lambda key: "dummy", raising=False
    )

    settings = {
        "latitude": 32.7,
        "longitude": -117.1,
        "units": "imperial",
        "weatherProvider": "OpenWeatherMap",
        "displayMetrics": "true",
        "displayForecast": "true",
        "displayGraph": "false",
        "titleSelection": "custom",
        "customTitle": "Test City",
        "weatherTimeZone": "localTimeZone",
    }

    # Build template params as generate_image would, but render HTML directly
    tzname = device_config_dev.get_config("timezone", default="America/New_York")
    import pytz
    tz = pytz.timezone(tzname)
    time_format = device_config_dev.get_config("time_format", default="12h")

    data = w.parse_weather_data(fake_get_weather_data("k", "imperial", 0, 0), fake_get_air_quality("k", 0, 0), tz, "imperial", time_format)
    data["title"] = settings["customTitle"]

    # Dimensions and assets
    dims = device_config_dev.get_resolution()
    if device_config_dev.get_config("orientation") == "vertical":
        dims = dims[::-1]

    from plugins.base_plugin.base_plugin import BASE_PLUGIN_RENDER_DIR
    import os
    style_sheets = [
        w.to_file_url(os.path.join(BASE_PLUGIN_RENDER_DIR, "plugin.css")),
        w.to_file_url(os.path.join(w.render_dir, "weather.css")),
    ]

    from utils.app_utils import get_fonts
    fonts = get_fonts()
    for f in fonts:
        f["url"] = w.to_file_url(f["url"])

    template_params = {
        **data,
        "plugin_settings": {
            **settings,
            "forecastDays": 7,
            "displayRefreshTime": "true",
            "moonPhase": "false",
        },
        "style_sheets": style_sheets,
        "font_faces": fonts,
        "width": dims[0],
        "height": dims[1],
    }

    template = w.env.get_template("weather.html")
    html = template.render(template_params)

    from playwright.sync_api import sync_playwright

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html.encode("utf-8"))
        html_path = f.name

    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--allow-file-access-from-files",
            "--enable-local-file-accesses",
        ])
        page = browser.new_page()
        page.goto("file://" + html_path)

        # Ensure at least one img tag with a data: or file:// src resolves dimensions
        imgs = page.query_selector_all("img")
        assert imgs, "No <img> tags found in weather template"
        loaded = 0
        for img in imgs:
            src = img.get_attribute("src") or ""
            if src.startswith("file://") or src.startswith("data:"):
                # Wait for load and check naturalWidth
                page.evaluate(
                    "img => new Promise(r => { if (img.complete) r(); else img.onload = () => r(); })",
                    img,
                )
                nw = page.evaluate("img => img.naturalWidth", img)
                if (nw or 0) > 0:
                    loaded += 1
        assert loaded > 0, "No local images loaded in weather UI"
        browser.close()
        try:
            os.remove(html_path)
        except Exception:
            pass



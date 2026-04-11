"""Plugin render pipeline benchmarks for InkyPi.

These benchmarks measure the hot path users wait on when clicking "Update Preview":
plugin Python code, HTML templating, and image post-processing.  They are
deterministic, hermetic, and network-free (all I/O is mocked).  Each benchmark
should complete well under 1 second on a CI runner.

See also: docs/benchmarking.md for the production benchmarking workflow.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_device_config(
    dimensions=(800, 480), orientation="horizontal", timezone="UTC"
):
    """Return a minimal MagicMock that satisfies BasePlugin / generate_image contracts."""
    cfg = MagicMock()
    cfg.get_resolution.return_value = list(dimensions)
    cfg.get_config.side_effect = lambda key, default=None: {
        "orientation": orientation,
        "timezone": timezone,
        "time_format": "24h",
    }.get(key, default)
    cfg.load_env_key.return_value = None
    return cfg


def _fake_screenshot(html, dimensions, timeout_ms=None):
    """Stub that returns a plain white image instead of spawning Chromium."""
    w, h = dimensions
    return Image.new("RGB", (w, h), "white")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXED_DT = datetime(2024, 6, 15, 14, 30, 0)  # deterministic: 2024-06-15 14:30

_OPEN_METEO_FORECAST = {
    "current_weather": {
        "time": "2024-06-15T14:00",
        "temperature": 21.0,
        "weathercode": 1,
    },
    "daily": {
        "time": ["2024-06-15", "2024-06-16", "2024-06-17"],
        "temperature_2m_max": [25.0, 24.0, 22.0],
        "temperature_2m_min": [15.0, 14.0, 13.0],
        "weathercode": [1, 2, 3],
        "sunrise": [
            "2024-06-15T05:30",
            "2024-06-16T05:31",
            "2024-06-17T05:32",
        ],
        "sunset": [
            "2024-06-15T20:45",
            "2024-06-16T20:44",
            "2024-06-17T20:43",
        ],
    },
    "hourly": {
        "time": [f"2024-06-15T{h:02d}:00" for h in range(24)],
        "temperature_2m": [20.0 + h * 0.1 for h in range(24)],
        "precipitation_probability": [5] * 24,
        "precipitation": [0.0] * 24,
        "relative_humidity_2m": [60] * 24,
        "surface_pressure": [1013] * 24,
        "visibility": [10000] * 24,
    },
}

_OPEN_METEO_AQI = {
    "hourly": {
        "time": ["2024-06-15T14:00"],
        "uv_index": [3.5],
        "european_aqi": [25],
    }
}


@pytest.fixture()
def device_cfg():
    return _make_device_config()


# ---------------------------------------------------------------------------
# 1. Clock plugin render
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="plugin_render")
def test_bench_clock_render(benchmark, device_cfg):
    """Measure the full Clock.generate_image() render pipeline.

    Uses a fixed datetime so results are deterministic across runs.
    The screenshot step is stubbed to return a plain white image — this mirrors
    the autouse mock_screenshot fixture in conftest.py but is explicit here for
    clarity and to avoid relying on autouse ordering in benchmark runs.
    """
    from plugins.clock.clock import Clock

    clock = Clock({"id": "clock"})
    settings = {
        "selectedClockFace": "Digital Clock",
        "primaryColor": "#ffffff",
        "secondaryColor": "#000000",
    }

    with (
        patch("plugins.base_plugin.base_plugin.take_screenshot_html", _fake_screenshot),
        patch("utils.image_utils.take_screenshot_html", _fake_screenshot),
        patch("plugins.clock.clock.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = FIXED_DT
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        result = benchmark(clock.generate_image, settings, device_cfg)

    assert isinstance(result, Image.Image)
    assert result.size == tuple(device_cfg.get_resolution())


# ---------------------------------------------------------------------------
# 2. Weather plugin render (Open-Meteo, mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="plugin_render")
def test_bench_weather_render(benchmark, device_cfg):
    """Measure the full Weather.generate_image() pipeline with a mocked Open-Meteo response.

    No real network calls are made.  The screenshot step is stubbed so only
    Python-side work (data parsing, Jinja2 templating, PIL) is measured.
    """
    from plugins.weather.weather import Weather

    weather = Weather({"id": "weather"})
    settings = {
        "latitude": "40.7128",
        "longitude": "-74.0060",
        "units": "metric",
        "weatherProvider": "OpenMeteo",
        "customTitle": "Test City",
        "displayForecast": "true",
        "forecastDays": "3",
    }

    mock_session = MagicMock()

    def _open_meteo_get(url, timeout=20):
        resp = MagicMock()
        resp.status_code = 200
        if "air-quality" in url:
            resp.json.return_value = _OPEN_METEO_AQI
        else:
            resp.json.return_value = _OPEN_METEO_FORECAST
        return resp

    mock_session.get.side_effect = _open_meteo_get

    with (
        patch(
            "plugins.weather.weather_api.get_http_session", return_value=mock_session
        ),
        patch("plugins.base_plugin.base_plugin.take_screenshot_html", _fake_screenshot),
        patch("utils.image_utils.take_screenshot_html", _fake_screenshot),
    ):

        result = benchmark(weather.generate_image, settings, device_cfg)

    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 3. HTML→PIL pipeline (base plugin render_image via plugin.html)
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="plugin_render")
def test_bench_html_render(benchmark, device_cfg):
    """Measure the BasePlugin.render_image() HTML→PIL pipeline directly.

    Uses the base plugin's own plugin.html template (the fallback template
    shipped with all plugins) with a minimal params dict.  This isolates the
    Jinja2 render + stubbed screenshot path from plugin-specific data fetching
    and PIL drawing, measuring the common HTML→image hot path shared by all
    HTML-rendered plugins.
    """
    from plugins.clock.clock import Clock

    # Clock is a pure-PIL plugin; its BasePlugin initialises the Jinja
    # environment pointing at base_plugin/render/ (which ships plugin.html).
    # Calling render_image with plugin.html + no CSS exercises the full
    # Jinja2→screenshot pipeline without depending on a plugin-specific template.
    plugin = Clock({"id": "clock"})
    dimensions = (800, 480)

    # Minimal params: plugin.html only needs plugin_settings for frame logic.
    template_params: dict = {
        "plugin_settings": {},
    }

    with (
        patch("plugins.base_plugin.base_plugin.take_screenshot_html", _fake_screenshot),
        patch("utils.image_utils.take_screenshot_html", _fake_screenshot),
    ):

        result = benchmark(
            plugin.render_image,
            dimensions,
            "plugin.html",
            None,  # no plugin-specific CSS — uses base plugin.css only
            template_params,
        )

    assert isinstance(result, Image.Image)
    assert result.size == dimensions

"""JTN-784: plugins with no user configuration should render via defaults.

Each test stubs the network / render sink so we can assert the defaults
selected by `generate_image` when called with an empty settings dict,
without spinning up chromium or hitting the real feed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest


class DummyDeviceConfig:
    def __init__(self) -> None:
        self._config = {"timezone": "UTC", "time_format": "24h"}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def load_env_key(self, key: str) -> str | None:
        return None

    def get_resolution(self) -> tuple[int, int]:
        return (800, 480)


def _plugin(cls, plugin_id: str):
    return cls({"id": plugin_id})


def test_comic_defaults_to_xkcd_when_settings_empty(monkeypatch):
    from src.plugins.comic import comic_parser as cp
    from src.plugins.comic.comic import Comic

    captured: dict[str, Any] = {}

    def fake_get_panel(name: str) -> dict[str, Any]:
        captured["comic"] = name
        return {
            "image_url": "https://example.invalid/x.png",
            "title": "",
            "caption": "",
        }

    monkeypatch.setattr(cp, "get_panel", fake_get_panel)
    # comic.py imports get_panel into its module namespace
    from src.plugins.comic import comic as comic_mod

    monkeypatch.setattr(comic_mod, "get_panel", fake_get_panel)

    def fake_compose(*_args, **_kwargs):
        return object()

    inst = _plugin(Comic, "comic")
    monkeypatch.setattr(inst, "_compose_image", fake_compose)

    # Expected defaults: comic=XKCD. No exception.
    inst.generate_image({}, DummyDeviceConfig())
    assert captured["comic"] == "XKCD"


def test_countdown_defaults_title_and_date_when_empty(monkeypatch):
    from src.plugins.countdown.countdown import Countdown

    captured: dict[str, Any] = {}

    def fake_render(_dims, _html, _css, params):
        captured["title"] = params["title"]
        captured["day_count"] = params["day_count"]
        captured["label"] = params["label"]
        return object()

    inst = _plugin(Countdown, "countdown")
    monkeypatch.setattr(inst, "render_image", fake_render)

    inst.generate_image({}, DummyDeviceConfig())
    assert captured["title"] == "Countdown"
    # Default is ~30 days out, so day_count must be positive.
    assert captured["day_count"] > 0
    assert captured["label"] == "Days Left"


def test_newspaper_defaults_slug_when_empty(monkeypatch):
    from src.plugins.newspaper import newspaper as np_mod
    from src.plugins.newspaper.newspaper import Newspaper

    captured: dict[str, Any] = {}

    class _FakeImage:
        size = (800, 480)

        def resize(self, *_a, **_kw):
            return self

    def fake_get_image(url: str):
        captured["url"] = url
        return _FakeImage()

    monkeypatch.setattr(np_mod, "get_image", fake_get_image)

    inst = _plugin(Newspaper, "newspaper")
    inst.generate_image({}, DummyDeviceConfig())
    # Default is NY_NYT; URL contains the slug lowercased-per-format.
    assert "NY_NYT" in captured["url"]


def test_rss_defaults_feed_url_when_empty(monkeypatch):
    from src.plugins.rss.rss import Rss

    captured: dict[str, Any] = {}

    def fake_parse(self, url: str, timeout: int = 10):  # noqa: ANN001
        captured["url"] = url
        return []

    def fake_render(_dims, _html, _css, params):
        captured["title"] = params["title"]
        return object()

    inst = _plugin(Rss, "rss")
    monkeypatch.setattr(Rss, "parse_rss_feed", fake_parse)
    monkeypatch.setattr(inst, "render_image", fake_render)

    inst.generate_image({}, DummyDeviceConfig())
    assert captured["url"] == "https://feeds.bbci.co.uk/news/rss.xml"
    assert captured["title"] == "Top Stories"


def test_weather_defaults_use_openmeteo_when_empty(monkeypatch):
    from src.plugins.weather.weather import Weather

    captured: dict[str, Any] = {}

    def fake_get_open_meteo_data(self, lat, long, units, days):  # noqa: ANN001
        captured["lat"] = lat
        captured["long"] = long
        captured["units"] = units
        return {}

    def fake_get_open_meteo_air_quality(self, lat, long):  # noqa: ANN001
        return {}

    def fake_parse_open_meteo_data(self, *_a, **_kw):
        return {"title": "-", "dt": datetime.now(UTC).timestamp()}

    def fake_render(_dims, _html, _css, params):
        captured["title"] = params.get("title")
        return object()

    inst = _plugin(Weather, "weather")
    monkeypatch.setattr(Weather, "get_open_meteo_data", fake_get_open_meteo_data)
    monkeypatch.setattr(
        Weather, "get_open_meteo_air_quality", fake_get_open_meteo_air_quality
    )
    monkeypatch.setattr(Weather, "parse_open_meteo_data", fake_parse_open_meteo_data)
    monkeypatch.setattr(inst, "render_image", fake_render)
    monkeypatch.setattr(inst, "_request_timeout", lambda: None)
    monkeypatch.setattr(inst, "get_plugin_dir", lambda p=None: "")

    inst.generate_image({}, DummyDeviceConfig())
    # NYC defaults, imperial, and OpenMeteo path used (not OWM; load_env_key
    # returns None here, so OWM path would raise "API Key not configured").
    assert captured["lat"] == pytest.approx(40.7128)
    assert captured["long"] == pytest.approx(-74.0060)
    assert captured["units"] == "imperial"

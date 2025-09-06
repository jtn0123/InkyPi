from datetime import UTC, datetime

import pytest
import pytz

from src.plugins.weather.weather import Weather


class DummyConfig(dict):
    def get(self, k, default=None):
        return super().get(k, default)


class DummyDeviceConfig:
    def __init__(self):
        self._tz = "UTC"
        self._res = (200, 200)
        self._config = {"timezone": "UTC", "time_format": "24h"}

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def load_env_key(self, key):
        return "FAKE"

    def get_resolution(self):
        return self._res


@pytest.fixture
def weather_plugin(tmp_path, monkeypatch):
    config = DummyConfig({"id": "weather"})
    w = Weather(config)
    # monkeypatch get_plugin_dir to return tmp path for icons
    monkeypatch.setattr(w, "get_plugin_dir", lambda p=None: str(tmp_path / (p or "")))
    return w


def test_map_weather_code_to_icon_various_codes(weather_plugin):
    w = weather_plugin
    assert w.map_weather_code_to_icon(0, 12) == "01d"
    assert w.map_weather_code_to_icon(1, 12) == "02d"
    assert w.map_weather_code_to_icon(2, 12) == "03d"
    assert w.map_weather_code_to_icon(3, 12) == "04d"
    assert w.map_weather_code_to_icon(45, 12) == "50d"
    assert w.map_weather_code_to_icon(51, 12) == "09d"
    assert w.map_weather_code_to_icon(61, 12) == "10d"
    assert w.map_weather_code_to_icon(71, 12) == "13d"
    assert w.map_weather_code_to_icon(95, 12) == "11d"


def test_format_time_24h_and_12h():
    dt = datetime(2020, 1, 1, 5, 30, tzinfo=UTC)
    w = Weather({"id": "weather"})
    # 24h
    assert w.format_time(dt, "24h", hour_only=False).startswith("05:")
    # 12h with AM/PM
    res = w.format_time(dt, "12h", hour_only=False)
    assert "AM" in res or "am" in res


def test_parse_forecast_basic(weather_plugin):
    w = weather_plugin
    # create two-day daily forecast
    now = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    daily = [
        {
            "dt": now,
            "weather": [{"icon": "10n"}],
            "moon_phase": 0.25,
            "temp": {"max": 10, "min": 2},
        },
        {
            "dt": now + 86400,
            "weather": [{"icon": "01n"}],
            "moon_phase": 0.5,
            "temp": {"max": 12, "min": 3},
        },
    ]
    res = w.parse_forecast(daily, pytz.timezone("UTC"))
    assert len(res) == 2
    assert res[0]["high"] == 10
    assert res[1]["icon"].endswith("01d.png")


def test_parse_open_meteo_forecast_handles_api_and_fallback(
    monkeypatch, weather_plugin
):
    w = weather_plugin
    tz = pytz.timezone("UTC")
    # create daily_data with one day
    time_str = "2023-01-01T00:00"
    daily = {
        "time": [time_str],
        "weathercode": [0],
        "temperature_2m_max": [15],
        "temperature_2m_min": [5],
    }

    # mock requests.get for farmsense
    class DummyResp:
        def __init__(self, json_data):
            self._json = json_data

        def json(self):
            return self._json

    monkeypatch.setattr(
        "src.plugins.weather.weather.http_get",
        lambda *args, **kwargs: DummyResp(
            [{"Phase": "Full Moon", "Illumination": 0.5}]
        ),
    )
    res = w.parse_open_meteo_forecast(daily, tz)
    assert isinstance(res, list)
    assert res[0]["high"] == 15
    assert res[0]["moon_phase_pct"] == "50"


def test_parse_hourly_and_unit_conversion(weather_plugin):
    w = weather_plugin
    now = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    hourly = [
        {
            "dt": now + i * 3600,
            "temp": 10 + i,
            "pop": 0.1 * i,
            "rain": {"1h": 10 * (i + 1)},
        }
        for i in range(3)
    ]
    res_metric = w.parse_hourly(hourly, pytz.timezone("UTC"), "24h", "metric")
    assert res_metric[0]["rain"] == 10.0
    res_imperial = w.parse_hourly(hourly, pytz.timezone("UTC"), "24h", "imperial")
    # 10 mm -> inches conversion approx 0.3937
    assert round(res_imperial[0]["rain"], 2) == round(10 / 25.4, 2)


def test_parse_timezone_and_errors():
    w = Weather({"id": "weather"})
    with pytest.raises(RuntimeError):
        w.parse_timezone({})
    # valid
    tz = w.parse_timezone({"timezone": "UTC"})
    assert str(tz) == "UTC"


def test_parse_data_points_and_open_meteo_points(weather_plugin):
    w = weather_plugin
    # prepare simple weather and air_quality for OpenWeatherMap style
    now = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    weather = {
        "current": {
            "dt": now,
            "sunrise": now - 3600,
            "sunset": now + 3600,
            "wind_speed": 5,
            "humidity": 80,
            "pressure": 1012,
            "uvi": 3,
            "visibility": 12000,
            "weather": [{"icon": "01d"}],
        }
    }
    air_quality = {"list": [{"main": {"aqi": 2}}]}
    points = w.parse_data_points(
        weather, air_quality, pytz.timezone("UTC"), "metric", "24h"
    )
    labels = [p["label"] for p in points]
    assert "Sunrise" in labels and "Sunset" in labels and "Air Quality" in labels

    # Open-Meteo style
    weather_data = {
        "current_weather": {
            "time": "2020-01-01T00:00",
            "temperature": 5,
            "apparent_temperature": 4,
            "windspeed": 3,
        },
        "daily": {"sunrise": ["2020-01-01T07:00"], "sunset": ["2020-01-01T17:00"]},
        "hourly": {
            "time": ["2020-01-01T00:00"],
            "relative_humidity_2m": [50],
            "surface_pressure": [1015],
            "visibility": [10000],
        },
    }
    aqi_data = {
        "hourly": {"time": ["2020-01-01T00:00"], "uv_index": [1], "european_aqi": [10]}
    }
    points2 = w.parse_open_meteo_data_points(
        weather_data, aqi_data, pytz.timezone("UTC"), "metric", "24h"
    )
    labels2 = [p["label"] for p in points2]
    assert "Visibility" in labels2 and "Air Quality" in labels2

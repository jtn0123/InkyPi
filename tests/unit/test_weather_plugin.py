from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfoNotFoundError

import pytest

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
    assert w.map_weather_code_to_icon(1, 12) == "02d"  # Mainly clear
    assert (
        w.map_weather_code_to_icon(2, 12) == "02d"
    )  # Partly cloudy (upstream changed)
    assert w.map_weather_code_to_icon(3, 12) == "04d"
    assert w.map_weather_code_to_icon(45, 12) == "50d"
    assert (
        w.map_weather_code_to_icon(51, 12) == "51d"
    )  # Light drizzle (upstream changed)
    assert w.map_weather_code_to_icon(61, 12) == "51d"  # Light rain (upstream changed)
    assert w.map_weather_code_to_icon(71, 12) == "71d"  # Light snow (upstream changed)
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
    res = w.parse_forecast(daily, UTC, "d", 40.7)
    assert len(res) == 2
    assert res[0]["high"] == 10
    assert res[1]["icon"].endswith("01d.png")


def test_parse_open_meteo_forecast_uses_local_phase(monkeypatch, weather_plugin):
    w = weather_plugin
    tz = UTC
    daily = {
        "time": ["2023-01-01T00:00"],
        "weathercode": [0],
        "temperature_2m_max": [15],
        "temperature_2m_min": [5],
    }

    # Mock the astral moon.phase function used by upstream
    from astral import moon

    monkeypatch.setattr(moon, "phase", lambda dt: 14.75)  # Full moon phase age
    res = w.parse_open_meteo_forecast(daily, tz, 1, 40.7)  # is_day=1, lat=40.7
    assert isinstance(res, list)
    assert res[0]["high"] == 15
    # Full moon (phase_age ~14.75) results in ~100% illumination
    assert int(res[0]["moon_phase_pct"]) >= 95
    assert res[0]["moon_phase_icon"].endswith("fullmoon.png")


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
    res_metric = w.parse_hourly(hourly, UTC, "24h", "metric")
    assert res_metric[0]["rain"] == 10.0
    res_imperial = w.parse_hourly(hourly, UTC, "24h", "imperial")
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
    points = w.parse_data_points(weather, air_quality, UTC, "metric", "24h")
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
        weather_data, aqi_data, UTC, "metric", "24h"
    )
    labels2 = [p["label"] for p in points2]
    assert "Visibility" in labels2
    assert "Air Quality" in labels2


def test_open_meteo_moon_phase_error_fallback(monkeypatch, weather_plugin):
    w = weather_plugin
    tz = UTC
    daily = {
        "time": ["2025-01-01T00:00"],
        "weathercode": [0],
        "temperature_2m_max": [20],
        "temperature_2m_min": [10],
    }

    def boom(dt):
        raise RuntimeError("boom")

    # Mock moon.phase to raise error (upstream uses astral library)
    from astral import moon

    monkeypatch.setattr(moon, "phase", boom)
    res = w.parse_open_meteo_forecast(daily, tz, 1, 40.7)
    assert res and res[0]["moon_phase_pct"] == "0"
    assert res[0]["moon_phase_icon"].endswith("newmoon.png")


def test_open_meteo_unknown_code_maps_default(weather_plugin):
    w = weather_plugin
    # Code not in mapping should return default "01d"
    assert w.map_weather_code_to_icon(12345, 12) == "01d"


def test_generate_settings_template(weather_plugin):
    w = weather_plugin
    template = w.generate_settings_template()
    assert template["api_key"]["required"] is True
    assert template["api_key"]["service"] == "OpenWeatherMap"
    assert template["api_key"]["expected_key"] == "OPEN_WEATHER_MAP_SECRET"
    assert template["style_settings"] is True


def test_get_weather_data_error_handling(weather_plugin, requests_mock):
    w = weather_plugin
    # Mock API to return error
    requests_mock.get(
        "https://api.openweathermap.org/data/3.0/onecall", status_code=401
    )

    with pytest.raises(RuntimeError):
        w.get_weather_data("bad_key", "metric", 40.7, -74.0)


def test_parse_timezone_missing_field(weather_plugin):
    w = weather_plugin
    # Missing timezone field should raise error
    with pytest.raises(RuntimeError):
        w.parse_timezone({})


def test_parse_timezone_invalid_value(weather_plugin):
    w = weather_plugin
    # Invalid timezone should raise error
    with pytest.raises(ZoneInfoNotFoundError):
        w.parse_timezone({"timezone": "Invalid/Timezone"})


# ---------------------------------------------------------------------------
# _get_current_hourly_value helper tests
# ---------------------------------------------------------------------------


class TestGetCurrentHourlyValue:
    def test_matching_hour(self):
        from plugins.weather.weather_data import _get_current_hourly_value

        tz = UTC
        current = datetime(2025, 6, 15, 10, 30, tzinfo=tz)
        times = [
            "2025-06-15T09:00+00:00",
            "2025-06-15T10:00+00:00",
            "2025-06-15T11:00+00:00",
        ]
        values = [50, 65, 70]
        assert _get_current_hourly_value(times, values, tz, current, "test") == 65

    def test_no_matching_hour(self):
        from plugins.weather.weather_data import _get_current_hourly_value

        tz = UTC
        current = datetime(2025, 6, 15, 23, 0, tzinfo=tz)
        times = ["2025-06-15T09:00+00:00", "2025-06-15T10:00+00:00"]
        values = [50, 65]
        assert _get_current_hourly_value(times, values, tz, current, "test") == "N/A"

    def test_empty_lists(self):
        from plugins.weather.weather_data import _get_current_hourly_value

        tz = UTC
        current = datetime(2025, 6, 15, 10, 0, tzinfo=tz)
        assert _get_current_hourly_value([], [], tz, current, "test") == "N/A"

    def test_invalid_time_string_skipped(self):
        from plugins.weather.weather_data import _get_current_hourly_value

        tz = UTC
        current = datetime(2025, 6, 15, 10, 0, tzinfo=tz)
        times = ["not-a-date", "2025-06-15T10:00+00:00"]
        values = [99, 42]
        assert _get_current_hourly_value(times, values, tz, current, "test") == 42

    def test_index_beyond_values_returns_na(self):
        from plugins.weather.weather_data import _get_current_hourly_value

        tz = UTC
        current = datetime(2025, 6, 15, 10, 0, tzinfo=tz)
        times = ["2025-06-15T10:00+00:00"]
        values = []  # times has entry but values is empty
        assert _get_current_hourly_value(times, values, tz, current, "test") == "N/A"


class TestFormatOwmVisibility:
    """Tests for JTN-252: OWM visibility respects unit preference."""

    def test_metric_returns_km_value(self):
        from plugins.weather.weather_data import _format_owm_visibility

        # 5000 metres → 5.0 km, below 10 km threshold
        result = _format_owm_visibility(5000, "metric")
        assert result == 5.0

    def test_metric_above_threshold_prefixes_gt(self):
        from plugins.weather.weather_data import _format_owm_visibility

        # 10000 metres → 10.0 km, at threshold → ">10.0"
        result = _format_owm_visibility(10000, "metric")
        assert result == ">10.0"

    def test_imperial_converts_to_miles(self):
        from plugins.weather.weather_data import _format_owm_visibility

        # 8046.72 metres ≈ 5.0 miles
        result = _format_owm_visibility(8046.72, "imperial")
        assert result == 5.0

    def test_imperial_above_threshold_prefixes_gt(self):
        from plugins.weather.weather_data import _format_owm_visibility

        # 10000 metres ≈ 6.2 miles, at threshold → ">6.2"
        result = _format_owm_visibility(10000, "imperial")
        assert result == ">6.2"

    def test_none_visibility_returns_na(self):
        from plugins.weather.weather_data import _format_owm_visibility

        assert _format_owm_visibility(None, "imperial") == "N/A"
        assert _format_owm_visibility(None, "metric") == "N/A"


#: Far enough ahead that the hourly parser's "skip past hours already gone
#: today" filter never trims a fixture row, whatever day the suite runs on.
FUTURE_DAY = "2099-06-15"


class TestOpenMeteoUnitsAndIcons:
    """Regression cover for the Open-Meteo request/parse fixes.

    Open-Meteo has no Kelvin output mode and its legacy ``current_weather``
    block carries no apparent temperature, so "Standard" units failed outright
    and "feels like" silently mirrored the plain temperature.
    """

    def test_standard_units_request_celsius_not_kelvin(self) -> None:
        from plugins.weather.weather_api import OPEN_METEO_UNIT_PARAMS

        # Open-Meteo rejects temperature_unit=kelvin; we convert at parse time.
        assert "temperature_unit=celsius" in OPEN_METEO_UNIT_PARAMS["standard"]
        assert "kelvin" not in OPEN_METEO_UNIT_PARAMS["standard"]

    def test_forecast_url_requests_apparent_temperature_and_hourly_codes(self) -> None:
        from plugins.weather.weather_api import OPEN_METEO_FORECAST_URL

        assert "apparent_temperature" in OPEN_METEO_FORECAST_URL
        assert "hourly=weather_code" in OPEN_METEO_FORECAST_URL
        assert "current_weather=true" not in OPEN_METEO_FORECAST_URL

    def test_to_display_temperature_shifts_only_standard(self) -> None:
        from plugins.weather.weather_data import to_display_temperature

        assert to_display_temperature(0, "standard") == pytest.approx(273.15)
        assert to_display_temperature(0, "metric") == 0
        assert to_display_temperature(50, "imperial") == 50
        # A malformed reading degrades to zero rather than raising mid-render.
        assert to_display_temperature("n/a", "metric") == 0.0

    def test_current_block_normalises_modern_and_legacy_shapes(self) -> None:
        from plugins.weather.weather_data import _open_meteo_current

        modern = _open_meteo_current(
            {
                "current": {
                    "temperature_2m": 12,
                    "wind_speed_10m": 3,
                    "wind_direction_10m": 180,
                    "weather_code": 2,
                    "apparent_temperature": 10,
                }
            }
        )
        assert modern["temperature"] == 12
        assert modern["windspeed"] == 3
        assert modern["winddirection"] == 180
        assert modern["weathercode"] == 2
        # No legacy equivalent, so it passes through untouched.
        assert modern["apparent_temperature"] == 10

        legacy = _open_meteo_current({"current_weather": {"temperature": 7}})
        assert legacy["temperature"] == 7
        assert _open_meteo_current({}) == {}

    def test_feels_like_uses_apparent_temperature_when_present(
        self, weather_plugin: Any
    ) -> None:
        w = weather_plugin
        data = w.parse_open_meteo_data(
            {
                "current": {
                    "temperature_2m": 20,
                    "apparent_temperature": 26,
                    "weather_code": 0,
                    "is_day": 1,
                },
                "daily": {},
                "hourly": {},
            },
            {},
            UTC,
            "metric",
            "24h",
            40.7,
        )
        assert data["current_temperature"] == "20"
        assert data["feels_like"] == "26"

    def test_standard_units_convert_current_and_forecast_to_kelvin(
        self, weather_plugin
    ) -> None:
        w = weather_plugin
        data = w.parse_open_meteo_data(
            {
                "current": {
                    "temperature_2m": 0,
                    "apparent_temperature": 0,
                    "weather_code": 0,
                    "is_day": 1,
                },
                "daily": {
                    "time": ["2026-08-15"],
                    "weathercode": [0],
                    "temperature_2m_max": [10],
                    "temperature_2m_min": [0],
                },
                "hourly": {},
            },
            {},
            UTC,
            "standard",
            "24h",
            40.7,
        )
        assert data["current_temperature"] == "273"
        assert data["feels_like"] == "273"
        assert data["forecast"][0]["high"] == 283
        assert data["forecast"][0]["low"] == 273

    def test_moon_phase_uses_the_rendered_day_not_tomorrow(
        self, monkeypatch, weather_plugin
    ) -> None:
        from astral import moon

        seen = []
        monkeypatch.setattr(moon, "phase", lambda d: seen.append(d) or 14.75)
        weather_plugin.parse_open_meteo_forecast(
            {
                "time": ["2026-08-15"],
                "weathercode": [0],
                "temperature_2m_max": [15],
                "temperature_2m_min": [5],
            },
            UTC,
            1,
            40.7,
        )
        assert [d.isoformat() for d in seen] == ["2026-08-15"]

    def test_hourly_rows_carry_icons_derived_from_weather_codes(
        self, weather_plugin: Any
    ) -> None:
        # A future date keeps every row past the parser's "start at the current
        # hour" filter, so the assertion does not depend on the wall clock.
        # Open-Meteo returns naive local timestamps (timezone=auto); rows and
        # sunrise/sunset are parsed identically, so the day/night verdict holds
        # whatever the host timezone is.
        rows = weather_plugin.parse_open_meteo_hourly(
            {
                "time": [f"{FUTURE_DAY}T12:00", f"{FUTURE_DAY}T22:00"],
                "temperature_2m": [20, 15],
                "precipitation_probability": [0, 0],
                "precipitation": [0, 0],
                "weather_code": [0, 0],
            },
            UTC,
            "24h",
            sunrises=[f"{FUTURE_DAY}T06:00"],
            sunsets=[f"{FUTURE_DAY}T20:00"],
        )
        assert len(rows) == 2
        # Clear sky by day vs night resolves to the day/night icon pair.
        assert rows[0]["icon"].endswith("01d.png")
        assert rows[1]["icon"].endswith("01n.png")

    def test_hourly_rows_omit_icon_when_codes_absent(self, weather_plugin: Any) -> None:
        rows = weather_plugin.parse_open_meteo_hourly(
            {
                "time": [f"{FUTURE_DAY}T12:00"],
                "temperature_2m": [20],
                "precipitation_probability": [0],
                "precipitation": [0],
            },
            UTC,
            "24h",
        )
        # Falsy in the template rather than a path that does not exist.
        assert "icon" not in rows[0]


class TestWeatherIconPaths:
    """Every icon the plugin renders lives in <plugin_dir>/icons/."""

    def test_icon_path_points_into_the_icons_directory(self) -> None:
        from plugins.weather.weather_data import icon_path

        assert icon_path("/plugins/weather", "01d") == "/plugins/weather/icons/01d.png"

    def test_forecast_and_moon_icons_resolve_on_disk(self) -> None:
        import json
        import os

        from plugins.weather.weather import Weather
        from plugins.weather.weather_data import parse_open_meteo_forecast

        with open("src/plugins/weather/plugin-info.json") as handle:
            cfg = json.load(handle)
        plugin_dir = Weather(cfg).get_plugin_dir()
        rows = parse_open_meteo_forecast(
            {
                "time": ["2026-08-15"],
                "weathercode": [0],
                "temperature_2m_max": [20],
                "temperature_2m_min": [10],
            },
            UTC,
            1,
            40.7,
            plugin_dir,
        )
        assert os.path.exists(rows[0]["icon"]), rows[0]["icon"]
        assert os.path.exists(rows[0]["moon_phase_icon"]), rows[0]["moon_phase_icon"]


class TestOpenMeteoDataPointsUseTheNormalisedCurrentBlock:
    """Wind read 0 after the request moved to the modern `current=` block.

    `parse_open_meteo_data_points` still read `current_weather` directly, which
    no longer exists in responses, so the dashboard's Wind data point silently
    reported zero. Caught by CodeRabbit on PR #632.
    """

    def _wind(self, payload: dict[str, Any]) -> dict[str, Any]:
        from plugins.weather.weather_data import parse_open_meteo_data_points

        points = parse_open_meteo_data_points(
            payload, {}, UTC, "metric", "24h", "/plugins/weather"
        )
        return next(p for p in points if p["label"] == "Wind")

    def test_modern_current_block_supplies_wind(self) -> None:
        wind = self._wind(
            {
                "current": {
                    "temperature_2m": 20,
                    "wind_speed_10m": 5.4,
                    "wind_direction_10m": 180,
                },
                "daily": {},
                "hourly": {},
            }
        )
        assert wind["measurement"] == 5.4
        assert wind["arrow"], "a direction should resolve to an arrow glyph"

    def test_legacy_current_weather_block_still_works(self) -> None:
        """Cached responses predating the request change must not regress."""
        wind = self._wind(
            {
                "current_weather": {
                    "temperature": 20,
                    "windspeed": 5.4,
                    "winddirection": 180,
                },
                "daily": {},
                "hourly": {},
            }
        )
        assert wind["measurement"] == 5.4

    def test_absent_current_data_degrades_to_zero_rather_than_raising(self) -> None:
        assert self._wind({"daily": {}, "hourly": {}})["measurement"] == 0

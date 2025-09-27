from typing import Any


def _validate_openweather_schema(payload: dict[str, Any]) -> None:
    # Minimal loose schema: presence and types of commonly used keys
    assert isinstance(payload, dict)
    assert "current" in payload
    current = payload["current"]
    assert isinstance(current, dict)
    assert "dt" in current
    assert "temp" in current
    assert "weather" in current and isinstance(current["weather"], list)

    # daily and hourly are commonly present; allow empty lists
    assert "daily" in payload and isinstance(payload["daily"], list)
    assert "hourly" in payload and isinstance(payload["hourly"], list)


def _validate_openmeteo_schema(payload: dict[str, Any]) -> None:
    assert isinstance(payload, dict)
    assert "current_weather" in payload and isinstance(payload["current_weather"], dict)
    cw = payload["current_weather"]
    assert "time" in cw and "temperature" in cw
    assert "daily" in payload and isinstance(payload["daily"], dict)
    assert "hourly" in payload and isinstance(payload["hourly"], dict)


def test_openweather_schema_loose_example():
    # Example minimal valid structure
    payload = {
        "timezone": "UTC",
        "current": {
            "dt": 1700000000,
            "temp": 20,
            "weather": [{"icon": "01d"}],
        },
        "daily": [],
        "hourly": [],
    }
    _validate_openweather_schema(payload)


def test_openmeteo_schema_loose_example():
    payload = {
        "current_weather": {"time": "2025-01-01T12:00", "temperature": 21, "weathercode": 1},
        "daily": {"time": ["2025-01-01"], "temperature_2m_max": [25], "temperature_2m_min": [10], "weathercode": [1]},
        "hourly": {"time": ["2025-01-01T12:00"], "temperature_2m": [21]},
    }
    _validate_openmeteo_schema(payload)




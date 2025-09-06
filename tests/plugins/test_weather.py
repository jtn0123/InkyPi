# pyright: reportMissingImports=false


def test_weather_openweathermap_success(client, monkeypatch):
    import os
    os.environ['OPEN_WEATHER_MAP_SECRET'] = 'key'

    # Mock OWM endpoints
    import requests
    def fake_get(url, *args, **kwargs):
        class R:
            status_code = 200
            def json(self_inner):
                if 'air_pollution' in url:
                    return {"list": [{"main": {"aqi": 3}}]}
                if 'geo/1.0/reverse' in url:
                    return [{"name": "City", "state": "ST", "country": "US"}]
                # weather one-call
                return {
                    "timezone": "UTC",
                    "current": {"dt": 1700000000, "temp": 20, "feels_like": 20, "weather": [{"icon": "01d"}], "humidity": 50, "pressure": 1010, "uvi": 1, "visibility": 5000, "wind_speed": 3},
                    "daily": [
                        {"dt": 1700000000, "weather": [{"icon": "01d"}], "temp": {"max": 22, "min": 10}, "moon_phase": 0.1}
                    ],
                    "hourly": [
                        {"dt": 1700000000, "temp": 20, "pop": 0.1, "rain": {"1h": 0.0}}
                    ]
                }
        return R()

    monkeypatch.setattr(requests, 'get', fake_get, raising=True)

    data = {
        'plugin_id': 'weather',
        'latitude': '0',
        'longitude': '0',
        'units': 'metric',
        'weatherProvider': 'OpenWeatherMap',
        'titleSelection': 'location',
        'weatherTimeZone': 'configuredTimeZone',
    }
    resp = client.post('/update_now', data=data)
    assert resp.status_code == 200


def test_weather_openmeteo_success(client, monkeypatch):
    import requests
    def fake_get(url, *args, **kwargs):
        class R:
            status_code = 200
            def json(self_inner):
                if 'air-quality' in url:
                    return {"hourly": {"time": ["2025-01-01T12:00"], "uv_index": [3.5]}}
                # forecast
                return {
                    "current_weather": {"time": "2025-01-01T12:00", "temperature": 21, "weathercode": 1},
                    "daily": {
                        "time": ["2025-01-01"],
                        "temperature_2m_max": [25],
                        "temperature_2m_min": [10],
                        "weathercode": [1],
                        "sunrise": ["2025-01-01T07:00"],
                        "sunset": ["2025-01-01T17:00"],
                    },
                    "hourly": {
                        "time": ["2025-01-01T12:00"],
                        "temperature_2m": [21],
                        "precipitation_probability": [10],
                        "precipitation": [0.0],
                        "relative_humidity_2m": [50],
                        "surface_pressure": [1010],
                        "visibility": [10000]
                    }
                }
        return R()

    monkeypatch.setattr(requests, 'get', fake_get, raising=True)

    data = {
        'plugin_id': 'weather',
        'latitude': '0',
        'longitude': '0',
        'units': 'metric',
        'weatherProvider': 'OpenMeteo',
        'customTitle': 'My Weather',
    }
    resp = client.post('/update_now', data=data)
    assert resp.status_code == 200


def test_weather_save_settings(client, monkeypatch):
    """Test saving weather settings to default playlist from main plugin page."""
    # Mock the weather API calls
    import requests
    def fake_get(url, *args, **kwargs):
        class R:
            status_code = 200
            def json(self_inner):
                if 'air_pollution' in url:
                    return {"list": [{"main": {"aqi": 3}}]}
                if 'geo/1.0/reverse' in url:
                    return [{"name": "City", "state": "ST", "country": "US"}]
                # weather one-call
                return {
                    "timezone": "UTC",
                    "current": {"dt": 1700000000, "temp": 20, "feels_like": 20, "weather": [{"icon": "01d"}], "humidity": 50, "pressure": 1010, "uvi": 1, "visibility": 5000, "wind_speed": 3},
                    "daily": [
                        {"dt": 1700000000, "weather": [{"icon": "01d"}], "temp": {"max": 22, "min": 10}, "moon_phase": 0.1}
                    ],
                    "hourly": [
                        {"dt": 1700000000, "temp": 20, "pop": 0.1, "rain": {"1h": 0.0}}
                    ]
                }
        return R()

    monkeypatch.setattr(requests, 'get', fake_get, raising=True)

    data = {
        'plugin_id': 'weather',
        'latitude': '40.7128',
        'longitude': '-74.0060',
        'units': 'metric',
        'weatherProvider': 'OpenWeatherMap',
        'titleSelection': 'location',
        'weatherTimeZone': 'configuredTimeZone',
    }

    # Test saving settings
    resp = client.post('/save_plugin_settings', data=data)
    assert resp.status_code == 200
    result = resp.get_json()
    assert result['success'] is True
    assert 'weather_saved_settings' in result['instance_name']


def test_weather_settings_persistence(client, monkeypatch):
    """Test that saved weather settings persist when navigating back to plugin page."""
    # Mock the weather API calls
    import requests
    def fake_get(url, *args, **kwargs):
        class R:
            status_code = 200
            def json(self_inner):
                if 'air_pollution' in url:
                    return {"list": [{"main": {"aqi": 3}}]}
                if 'geo/1.0/reverse' in url:
                    return [{"name": "City", "state": "ST", "country": "US"}]
                # weather one-call
                return {
                    "timezone": "UTC",
                    "current": {"dt": 1700000000, "temp": 20, "feels_like": 20, "weather": [{"icon": "01d"}], "humidity": 50, "pressure": 1010, "uvi": 1, "visibility": 5000, "wind_speed": 3},
                    "daily": [
                        {"dt": 1700000000, "weather": [{"icon": "01d"}], "temp": {"max": 22, "min": 10}, "moon_phase": 0.1}
                    ],
                    "hourly": [
                        {"dt": 1700000000, "temp": 20, "pop": 0.1, "rain": {"1h": 0.0}}
                    ]
                }
        return R()

    monkeypatch.setattr(requests, 'get', fake_get, raising=True)

    data = {
        'plugin_id': 'weather',
        'latitude': '37.7749',
        'longitude': '-122.4194',
        'units': 'imperial',
        'weatherProvider': 'OpenWeatherMap',
        'titleSelection': 'location',
        'weatherTimeZone': 'configuredTimeZone',
    }

    # Save settings first
    resp = client.post('/save_plugin_settings', data=data)
    assert resp.status_code == 200

    # Now navigate to the plugin page without instance parameter
    # This should automatically load the saved settings
    resp = client.get('/plugin/weather')
    assert resp.status_code == 200

    # Check that the saved latitude and longitude are in the response
    response_text = resp.get_data(as_text=True)
    assert '37.7749' in response_text  # latitude
    assert '-122.4194' in response_text  # longitude



import logging

from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

WEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={long}&units={units}&exclude=minutely&appid={api_key}"
AIR_QUALITY_URL = "http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={long}&appid={api_key}"
GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={long}&limit=1&appid={api_key}"

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={long}&hourly=temperature_2m,precipitation,precipitation_probability,relative_humidity_2m,surface_pressure,visibility&daily=weathercode,temperature_2m_max,temperature_2m_min,sunrise,sunset&current_weather=true&timezone=auto&models=best_match&forecast_days={forecast_days}"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={long}&hourly=european_aqi,uv_index,uv_index_clear_sky&timezone=auto"
OPEN_METEO_UNIT_PARAMS = {
    "standard": "temperature_unit=kelvin&wind_speed_unit=ms&precipitation_unit=mm",
    "metric":   "temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm",
    "imperial": "temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
}


def get_weather_data(api_key, units, lat, long, timeout=20):
    url = WEATHER_URL.format(lat=lat, long=long, units=units, api_key=api_key)
    response = get_http_session().get(url, timeout=timeout)
    if not 200 <= response.status_code < 300:
        logger.error("Failed to retrieve weather data: %s", response.content)
        raise RuntimeError("Failed to retrieve weather data.")

    return response.json()


def get_air_quality(api_key, lat, long, timeout=20):
    url = AIR_QUALITY_URL.format(lat=lat, long=long, api_key=api_key)
    response = get_http_session().get(url, timeout=timeout)

    if not 200 <= response.status_code < 300:
        logger.error("Failed to get air quality data: %s", response.content)
        raise RuntimeError("Failed to retrieve air quality data.")

    return response.json()


def get_location(api_key, lat, long, timeout=20):
    url = GEOCODING_URL.format(lat=lat, long=long, api_key=api_key)
    response = get_http_session().get(url, timeout=timeout)

    if not 200 <= response.status_code < 300:
        logger.error(f"Failed to get location: {response.content}")
        raise RuntimeError("Failed to retrieve location.")

    location_list = response.json()
    if not location_list:
        logger.warning("Geocoding returned empty result for lat=%s, long=%s", lat, long)
        return "Unknown Location"
    location_data = location_list[0]
    location_str = f"{location_data.get('name')}, {location_data.get('state', location_data.get('country'))}"

    return location_str


def get_open_meteo_data(lat, long, units, forecast_days, timeout=20):
    unit_params = OPEN_METEO_UNIT_PARAMS[units]
    url = OPEN_METEO_FORECAST_URL.format(lat=lat, long=long, forecast_days=forecast_days) + f"&{unit_params}"
    response = get_http_session().get(url, timeout=timeout)

    if not 200 <= response.status_code < 300:
        logger.error("Failed to retrieve Open-Meteo weather data: %s", response.content)
        raise RuntimeError("Failed to retrieve Open-Meteo weather data.")

    return response.json()


def get_open_meteo_air_quality(lat, long, timeout=20):
    url = OPEN_METEO_AIR_QUALITY_URL.format(lat=lat, long=long)
    response = get_http_session().get(url, timeout=timeout)
    if not 200 <= response.status_code < 300:
        logger.error("Failed to retrieve Open-Meteo air quality data: %s", response.content)
        raise RuntimeError("Failed to retrieve Open-Meteo air quality data.")

    return response.json()

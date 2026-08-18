import logging
import os
from typing import Any

from utils.http_client import get_http_session
from utils.logging_utils import redact_secrets

logger = logging.getLogger(__name__)

_OWM_BASE = os.getenv("INKYPI_OPENWEATHER_API_URL", "https://api.openweathermap.org")
WEATHER_URL = f"{_OWM_BASE}/data/3.0/onecall?lat={{lat}}&lon={{long}}&units={{units}}&exclude=minutely&appid={{api_key}}"
AIR_QUALITY_URL = (
    f"{_OWM_BASE}/data/2.5/air_pollution?lat={{lat}}&lon={{long}}&appid={{api_key}}"
)
GEOCODING_URL = (
    f"{_OWM_BASE}/geo/1.0/reverse?lat={{lat}}&lon={{long}}&limit=1&appid={{api_key}}"
)

_OPEN_METEO_BASE = os.getenv("INKYPI_OPEN_METEO_API_URL", "https://api.open-meteo.com")
_OPEN_METEO_AQI_BASE = os.getenv(
    "INKYPI_OPEN_METEO_AQI_API_URL", "https://air-quality-api.open-meteo.com"
)
#: Current-conditions variables requested from Open-Meteo.
#
# Replaces the legacy ``current_weather=true`` block, which carries only
# temperature/windspeed/winddirection/weathercode/is_day.  In particular it has
# no ``apparent_temperature``, so the "feels like" reading silently fell back to
# the plain temperature for every Open-Meteo user.  The modern ``current=``
# parameter lets us ask for it explicitly.  Response keys match these names
# (``temperature_2m`` etc.), which is why ``_open_meteo_current()`` in
# weather_data.py normalises both spellings.
OPEN_METEO_CURRENT_FIELDS = (
    "temperature_2m,apparent_temperature,wind_speed_10m,wind_direction_10m,"
    "is_day,precipitation,weather_code"
)

#: Hourly variables. ``weather_code`` drives the per-hour icons on the forecast
#: graph (``displayGraphIcons``); without it ``hour.icon`` renders empty.
OPEN_METEO_HOURLY_FIELDS = (
    "weather_code,temperature_2m,precipitation,precipitation_probability,"
    "relative_humidity_2m,surface_pressure,visibility"
)

OPEN_METEO_FORECAST_URL = f"{_OPEN_METEO_BASE}/v1/forecast?latitude={{lat}}&longitude={{long}}&hourly={OPEN_METEO_HOURLY_FIELDS}&daily=weathercode,temperature_2m_max,temperature_2m_min,sunrise,sunset&current={OPEN_METEO_CURRENT_FIELDS}&timezone=auto&models=best_match&forecast_days={{forecast_days}}"
OPEN_METEO_AIR_QUALITY_URL = f"{_OPEN_METEO_AQI_BASE}/v1/air-quality?latitude={{lat}}&longitude={{long}}&hourly=european_aqi,uv_index,uv_index_clear_sky&timezone=auto"

# Open-Meteo accepts only ``celsius`` and ``fahrenheit`` for temperature_unit.
# "Standard" (Kelvin) is therefore requested in Celsius and converted at parse
# time by ``weather_data.to_display_temperature`` — sending
# ``temperature_unit=kelvin`` made the API reject the request outright.
OPEN_METEO_UNIT_PARAMS = {
    "standard": "temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm",
    "metric": "temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm",
    "imperial": "temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch",
}


def get_weather_data(
    api_key: str, units: str, lat: float, long: float, timeout: int | float = 20
) -> Any:
    url = WEATHER_URL.format(lat=lat, long=long, units=units, api_key=api_key)
    response = get_http_session().get(url, timeout=timeout)
    if not 200 <= response.status_code < 300:
        # CodeQL taints `response` because the enclosing function accepts
        # api_key; wrap with redact_secrets() to mask any accidental key
        # leakage in the error body before logging.
        logger.error(
            "Failed to retrieve weather data: %s", redact_secrets(response.content)
        )
        raise RuntimeError("Failed to retrieve weather data.")

    return response.json()


def get_air_quality(
    api_key: str, lat: float, long: float, timeout: int | float = 20
) -> Any:
    url = AIR_QUALITY_URL.format(lat=lat, long=long, api_key=api_key)
    response = get_http_session().get(url, timeout=timeout)

    if not 200 <= response.status_code < 300:
        logger.error(
            "Failed to get air quality data: %s", redact_secrets(response.content)
        )
        raise RuntimeError("Failed to retrieve air quality data.")

    return response.json()


def get_location(
    api_key: str, lat: float, long: float, timeout: int | float = 20
) -> str:
    url = GEOCODING_URL.format(lat=lat, long=long, api_key=api_key)
    response = get_http_session().get(url, timeout=timeout)

    if not 200 <= response.status_code < 300:
        logger.error("Failed to get location: %s", redact_secrets(response.content))
        raise RuntimeError("Failed to retrieve location.")

    location_list = response.json()
    if not location_list:
        logger.warning("Geocoding returned empty result for lat=%s, long=%s", lat, long)
        return "Unknown Location"
    location_data = location_list[0]
    return f"{location_data.get('name')}, {location_data.get('state', location_data.get('country'))}"


def get_open_meteo_data(
    lat: float,
    long: float,
    units: str,
    forecast_days: int,
    timeout: int | float = 20,
) -> Any:
    unit_params = OPEN_METEO_UNIT_PARAMS[units]
    url = (
        OPEN_METEO_FORECAST_URL.format(lat=lat, long=long, forecast_days=forecast_days)
        + f"&{unit_params}"
    )
    response = get_http_session().get(url, timeout=timeout)

    if not 200 <= response.status_code < 300:
        logger.error("Failed to retrieve Open-Meteo weather data: %s", response.content)
        raise RuntimeError("Failed to retrieve Open-Meteo weather data.")

    return response.json()


def get_open_meteo_air_quality(
    lat: float, long: float, timeout: int | float = 20
) -> Any:
    url = OPEN_METEO_AIR_QUALITY_URL.format(lat=lat, long=long)
    response = get_http_session().get(url, timeout=timeout)
    if not 200 <= response.status_code < 300:
        logger.error(
            "Failed to retrieve Open-Meteo air quality data: %s", response.content
        )
        raise RuntimeError("Failed to retrieve Open-Meteo air quality data.")

    return response.json()

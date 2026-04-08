import logging
import math
import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import moon

logger = logging.getLogger(__name__)


def _get_current_hourly_value(times, values, tz, current_time, label):
    """Find the value in *values* whose corresponding entry in *times* matches
    the current hour.  Returns ``"N/A"`` when no match is found or the time
    string cannot be parsed.
    """
    for i, time_str in enumerate(times):
        try:
            if (
                datetime.fromisoformat(time_str).astimezone(tz).hour
                == current_time.hour
            ):
                if i < len(values):
                    return values[i]
                return "N/A"
        except ValueError:
            logger.warning("Could not parse time string %s for %s.", time_str, label)
            continue
    return "N/A"


UNITS = {
    "standard": {"temperature": "K", "speed": "m/s"},
    "metric": {"temperature": "\u00b0C", "speed": "m/s"},
    "imperial": {"temperature": "\u00b0F", "speed": "mph"},
}


def get_moon_phase_name(phase_age: float) -> str:
    """Determines the name of the lunar phase based on the age of the moon."""
    PHASES_THRESHOLDS = [
        (1.0, "newmoon"),
        (7.0, "waxingcrescent"),
        (8.5, "firstquarter"),
        (14.0, "waxinggibbous"),
        (15.5, "fullmoon"),
        (22.0, "waninggibbous"),
        (23.5, "lastquarter"),
        (29.0, "waningcrescent"),
    ]

    for threshold, phase_name in PHASES_THRESHOLDS:
        if phase_age <= threshold:
            return phase_name
    return "newmoon"


def format_time(dt, time_format, hour_only=False, include_am_pm=True):
    """Format datetime based on 12h or 24h preference"""
    if time_format == "24h":
        return dt.strftime("%H:00" if hour_only else "%H:%M")

    if include_am_pm:
        fmt = "%I %p" if hour_only else "%I:%M %p"
    else:
        fmt = "%I" if hour_only else "%I:%M"

    return dt.strftime(fmt).lstrip("0")


def get_wind_arrow(wind_deg: float) -> str:
    DIRECTIONS = [
        ("\u2193", 22.5),  # North (N)
        ("\u2199", 67.5),  # North-East (NE)
        ("\u2190", 112.5),  # East (E)
        ("\u2196", 157.5),  # South-East (SE)
        ("\u2191", 202.5),  # South (S)
        ("\u2197", 247.5),  # South-West (SW)
        ("\u2192", 292.5),  # West (W)
        ("\u2198", 337.5),  # North-West (NW)
        ("\u2193", 360.0),  # Wrap back to North
    ]
    wind_deg = wind_deg % 360
    for arrow, upper_bound in DIRECTIONS:
        if wind_deg < upper_bound:
            return arrow

    return "\u2191"


def parse_timezone(weatherdata):
    """Parse timezone from weather data"""
    if "timezone" in weatherdata:
        logger.info(f"Using timezone from weather data: {weatherdata['timezone']}")
        return ZoneInfo(weatherdata["timezone"])
    else:
        logger.error("Failed to retrieve Timezone from weather data")
        raise RuntimeError("Timezone not found in weather data.")


_WEATHER_CODE_TO_ICON = {
    0: "01d",
    1: "02d",
    2: "02d",
    3: "04d",
    51: "51d",
    53: "53d",
    55: "09d",
    45: "50d",
    48: "48d",
    56: "56d",
    57: "57d",
    61: "51d",
    63: "53d",
    65: "09d",
    66: "56d",
    67: "57d",
    71: "71d",
    73: "73d",
    75: "13d",
    77: "77d",
    80: "51d",
    81: "53d",
    82: "09d",
    85: "71d",
    86: "13d",
    95: "11d",
    96: "11d",
    99: "11d",
}

_NIGHT_ICON_MAP = {
    "01d": "01n",
    "02d": "02n",
    "10d": "10n",
}


def map_weather_code_to_icon(weather_code, is_day):
    icon = _WEATHER_CODE_TO_ICON.get(weather_code, "01d")
    if is_day == 0:
        icon = _NIGHT_ICON_MAP.get(icon, icon)
    return icon


def get_moon_phase_icon_path(phase_name: str, lat: float, plugin_dir: str) -> str:
    """Determines the path to the moon icon, inverting it if the location is in the Southern Hemisphere."""
    # Waxing, Waning, First and Last quarter phases are inverted between hemispheres.
    if lat < 0:  # Southern Hemisphere
        if phase_name == "waxingcrescent":
            phase_name = "waningcrescent"
        elif phase_name == "waxinggibbous":
            phase_name = "waninggibbous"
        elif phase_name == "waningcrescent":
            phase_name = "waxingcrescent"
        elif phase_name == "waninggibbous":
            phase_name = "waxinggibbous"
        elif phase_name == "firstquarter":
            phase_name = "lastquarter"
        elif phase_name == "lastquarter":
            phase_name = "firstquarter"

    return os.path.join(plugin_dir, f"{phase_name}.png")


_MOON_PHASES = [
    (0.0, "newmoon"),
    (0.25, "firstquarter"),
    (0.5, "fullmoon"),
    (0.75, "lastquarter"),
    (1.0, "newmoon"),
]


def _choose_phase_name(phase: float) -> str:
    for target, name in _MOON_PHASES:
        if math.isclose(phase, target, abs_tol=1e-3):
            return name
    if 0.0 < phase < 0.25:
        return "waxingcrescent"
    elif 0.25 < phase < 0.5:
        return "waxinggibbous"
    elif 0.5 < phase < 0.75:
        return "waninggibbous"
    else:
        return "waningcrescent"


def parse_forecast(daily_forecast, tz, current_suffix, lat, plugin_dir):
    """
    - daily_forecast: list of daily entries from One-Call v3 (each has 'dt', 'weather', 'temp', 'moon_phase')
    - tz: your target tzinfo (e.g. from zoneinfo)
    """
    forecast = []
    icon_codes_to_apply_current_suffix = ["01", "02", "10"]
    for day in daily_forecast:
        # --- weather icon ---
        weather_icon = day["weather"][0]["icon"]  # e.g. "10d", "01n"
        icon_code = weather_icon[:2]
        if icon_code in icon_codes_to_apply_current_suffix:
            weather_icon_base = weather_icon[:-1]
            weather_icon = weather_icon_base + current_suffix
        else:
            if weather_icon.endswith("n"):
                weather_icon = weather_icon.replace("n", "d")
        weather_icon_path = os.path.join(plugin_dir, f"{weather_icon}.png")

        # --- moon phase & icon ---
        moon_phase = float(day["moon_phase"])  # [0.0-1.0]
        phase_name_north_hemi = _choose_phase_name(moon_phase)
        moon_icon_path = get_moon_phase_icon_path(
            phase_name_north_hemi, lat, plugin_dir
        )
        # --- true illumination percent, no decimals ---
        illum_fraction = (1 - math.cos(2 * math.pi * moon_phase)) / 2
        moon_pct = f"{illum_fraction * 100:.0f}"

        # --- date & temps ---
        dt = datetime.fromtimestamp(day["dt"], tz=UTC).astimezone(tz)
        day_label = dt.strftime("%a")

        forecast.append(
            {
                "day": day_label,
                "high": int(day["temp"]["max"]),
                "low": int(day["temp"]["min"]),
                "icon": weather_icon_path,
                "moon_phase_pct": moon_pct,
                "moon_phase_icon": moon_icon_path,
            }
        )

    return forecast


def parse_open_meteo_forecast(daily_data, tz, is_day, lat, plugin_dir):
    """
    Parse the daily forecast from Open-Meteo API and calculate moon phase and illumination using the local 'astral' library.
    """
    times = daily_data.get("time", [])
    weather_codes = daily_data.get("weathercode", [])
    temp_max = daily_data.get("temperature_2m_max", [])
    temp_min = daily_data.get("temperature_2m_min", [])

    forecast = []

    for i in range(0, len(times)):
        dt = datetime.fromisoformat(times[i])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        day_label = dt.strftime("%a")

        code = weather_codes[i] if i < len(weather_codes) else 0
        weather_icon = map_weather_code_to_icon(code, is_day)
        weather_icon_path = os.path.join(plugin_dir, f"{weather_icon}.png")

        target_date: date = dt.date() + timedelta(days=1)

        try:
            phase_age = moon.phase(target_date)
            phase_name_north_hemi = get_moon_phase_name(phase_age)
            LUNAR_CYCLE_DAYS = 29.530588853
            phase_fraction = phase_age / LUNAR_CYCLE_DAYS
            illum_pct = (1 - math.cos(2 * math.pi * phase_fraction)) / 2 * 100
        except Exception as e:
            logger.error(f"Error calculating moon phase for {target_date}: {e}")
            illum_pct = 0
            phase_name_north_hemi = "newmoon"
        moon_icon_path = get_moon_phase_icon_path(
            phase_name_north_hemi, lat, plugin_dir
        )

        forecast.append(
            {
                "day": day_label,
                "high": int(temp_max[i]) if i < len(temp_max) else 0,
                "low": int(temp_min[i]) if i < len(temp_min) else 0,
                "icon": weather_icon_path,
                "moon_phase_pct": f"{illum_pct:.0f}",
                "moon_phase_icon": moon_icon_path,
            }
        )

    return forecast


def parse_hourly(hourly_forecast, tz, time_format, units):
    hourly = []
    for hour in hourly_forecast[:24]:
        dt = datetime.fromtimestamp(hour.get("dt"), tz=UTC).astimezone(tz)
        rain_mm = hour.get("rain", {}).get("1h", 0.0)
        rain = rain_mm / 25.4 if units == "imperial" else rain_mm
        hour_forecast = {
            "time": format_time(dt, time_format, hour_only=True),
            "temperature": int(hour.get("temp")),
            "precipitation": hour.get("pop"),
            "rain": round(rain, 2),
        }
        hourly.append(hour_forecast)
    return hourly


def parse_open_meteo_hourly(hourly_data, tz, time_format):
    hourly = []
    times = hourly_data.get("time", [])
    temperatures = hourly_data.get("temperature_2m", [])
    precipitation_probabilities = hourly_data.get("precipitation_probability", [])
    rain = hourly_data.get("precipitation", [])
    current_time_in_tz = datetime.now(tz)
    start_index = 0
    for i, time_str in enumerate(times):
        try:
            dt_hourly = datetime.fromisoformat(time_str).astimezone(tz)
            if (
                dt_hourly.date() == current_time_in_tz.date()
                and dt_hourly.hour >= current_time_in_tz.hour
            ):
                start_index = i
                break
            if dt_hourly.date() > current_time_in_tz.date():
                break
        except ValueError:
            logger.warning(f"Could not parse time string {time_str} in hourly data.")
            continue

    sliced_times = times[start_index:]
    sliced_temperatures = temperatures[start_index:]
    sliced_precipitation_probabilities = precipitation_probabilities[start_index:]
    sliced_rain = rain[start_index:]

    for i in range(min(24, len(sliced_times))):
        dt = datetime.fromisoformat(sliced_times[i]).astimezone(tz)
        hour_forecast = {
            "time": format_time(dt, time_format, True),
            "temperature": (
                int(sliced_temperatures[i]) if i < len(sliced_temperatures) else 0
            ),
            "precipitation": (
                (sliced_precipitation_probabilities[i] / 100)
                if i < len(sliced_precipitation_probabilities)
                else 0
            ),
            "rain": (sliced_rain[i]) if i < len(sliced_rain) else 0,
        }
        hourly.append(hour_forecast)
    return hourly


_AQI_SCALE = ["Good", "Fair", "Moderate", "Poor", "Very Poor"]


def _format_owm_visibility(visibility_raw, units):
    if visibility_raw is not None:
        if units == "imperial":
            visibility = round(visibility_raw / 1609.34, 1)
            threshold = 6.2
        else:
            visibility = round(visibility_raw / 1000, 1)
            threshold = 10
        return f">{visibility}" if visibility >= threshold else visibility
    return "N/A"


def _format_owm_aqi(aqi):
    if aqi is not None:
        idx = max(0, min(int(aqi) - 1, len(_AQI_SCALE) - 1))
        return _AQI_SCALE[idx]
    return ""


def _build_sun_data_point(label, epoch, tz, time_format, plugin_dir, icon_name):
    if not epoch:
        return None
    dt = datetime.fromtimestamp(epoch, tz=UTC).astimezone(tz)
    return {
        "label": label,
        "measurement": format_time(dt, time_format, include_am_pm=False),
        "unit": "" if time_format == "24h" else dt.strftime("%p"),
        "icon": os.path.join(plugin_dir, f"icons/{icon_name}.png"),
    }


def parse_data_points(weather, air_quality, tz, units, time_format, plugin_dir):
    data_points = []
    current = weather.get("current", {})

    sunrise_point = _build_sun_data_point(
        "Sunrise", current.get("sunrise"), tz, time_format, plugin_dir, "sunrise"
    )
    if sunrise_point:
        data_points.append(sunrise_point)
    else:
        logger.info(
            "Sunrise not found in OpenWeatherMap response, this is expected for polar areas in midnight sun and polar night periods."
        )

    sunset_point = _build_sun_data_point(
        "Sunset", current.get("sunset"), tz, time_format, plugin_dir, "sunset"
    )
    if sunset_point:
        data_points.append(sunset_point)
    else:
        logger.info(
            "Sunset not found in OpenWeatherMap response, this is expected for polar areas in midnight sun and polar night periods."
        )

    wind_deg = current.get("wind_deg", 0)
    wind_arrow = get_wind_arrow(wind_deg)
    data_points.append(
        {
            "label": "Wind",
            "measurement": current.get("wind_speed"),
            "unit": UNITS[units]["speed"],
            "icon": os.path.join(plugin_dir, "icons/wind.png"),
            "arrow": wind_arrow,
        }
    )

    data_points.append(
        {
            "label": "Humidity",
            "measurement": current.get("humidity"),
            "unit": "%",
            "icon": os.path.join(plugin_dir, "icons/humidity.png"),
        }
    )

    data_points.append(
        {
            "label": "Pressure",
            "measurement": current.get("pressure"),
            "unit": "hPa",
            "icon": os.path.join(plugin_dir, "icons/pressure.png"),
        }
    )

    data_points.append(
        {
            "label": "UV Index",
            "measurement": current.get("uvi"),
            "unit": "",
            "icon": os.path.join(plugin_dir, "icons/uvi.png"),
        }
    )

    visibility_unit = "mi" if units == "imperial" else "km"
    visibility_str = _format_owm_visibility(current.get("visibility"), units)
    data_points.append(
        {
            "label": "Visibility",
            "measurement": visibility_str,
            "unit": visibility_unit,
            "icon": os.path.join(plugin_dir, "icons/visibility.png"),
        }
    )

    aqi_list = air_quality.get("list", [])
    aqi = aqi_list[0].get("main", {}).get("aqi") if aqi_list else None
    data_points.append(
        {
            "label": "Air Quality",
            "measurement": aqi if aqi is not None else "N/A",
            "unit": _format_owm_aqi(aqi),
            "icon": os.path.join(plugin_dir, "icons/aqi.png"),
        }
    )

    return data_points


_OPEN_METEO_AQI_SCALE = ["Good", "Fair", "Moderate", "Poor", "Very Poor", "Ext Poor"]


def _format_open_meteo_visibility(raw_visibility, units):
    if raw_visibility == "N/A":
        return "N/A"
    if units == "imperial":
        current_visibility = round(float(raw_visibility) / 1609.344, 1)
    else:
        current_visibility = round(raw_visibility / 1000, 1)
    threshold = 6.2 if units == "imperial" else 10
    if current_visibility >= threshold:
        return f">{current_visibility}"
    return current_visibility


def _format_open_meteo_aqi(raw_aqi):
    if raw_aqi == "N/A":
        return "N/A", ""
    current_aqi = round(raw_aqi, 1)
    scale = _OPEN_METEO_AQI_SCALE[min(int(current_aqi // 20), 5)]
    return current_aqi, scale


def _build_open_meteo_sun_point(
    times_list, label, tz, time_format, plugin_dir, icon_name
):
    if not times_list:
        return None
    dt = datetime.fromisoformat(times_list[0]).astimezone(tz)
    return {
        "label": label,
        "measurement": format_time(dt, time_format, include_am_pm=False),
        "unit": "" if time_format == "24h" else dt.strftime("%p"),
        "icon": os.path.join(plugin_dir, f"icons/{icon_name}.png"),
    }


def parse_open_meteo_data_points(
    weather_data, aqi_data, tz, units, time_format, plugin_dir
):
    """Parses current data points from Open-Meteo API response."""
    data_points = []
    daily_data = weather_data.get("daily", {})
    current_data = weather_data.get("current_weather", {})
    hourly_data = weather_data.get("hourly", {})

    current_time = datetime.now(tz)

    # Sunrise
    sunrise_point = _build_open_meteo_sun_point(
        daily_data.get("sunrise", []), "Sunrise", tz, time_format, plugin_dir, "sunrise"
    )
    if sunrise_point:
        data_points.append(sunrise_point)
    else:
        logger.info(
            "Sunrise not found in Open-Meteo response, this is expected for polar areas in midnight sun and polar night periods."
        )

    # Sunset
    sunset_point = _build_open_meteo_sun_point(
        daily_data.get("sunset", []), "Sunset", tz, time_format, plugin_dir, "sunset"
    )
    if sunset_point:
        data_points.append(sunset_point)
    else:
        logger.info(
            "Sunset not found in Open-Meteo response, this is expected for polar areas in midnight sun and polar night periods."
        )

    # Wind
    wind_speed = current_data.get("windspeed", 0)
    wind_deg = current_data.get("winddirection", 0)
    wind_arrow = get_wind_arrow(wind_deg)
    wind_unit = UNITS[units]["speed"]
    data_points.append(
        {
            "label": "Wind",
            "measurement": wind_speed,
            "unit": wind_unit,
            "icon": os.path.join(plugin_dir, "icons/wind.png"),
            "arrow": wind_arrow,
        }
    )

    # Humidity
    raw_humidity = _get_current_hourly_value(
        hourly_data.get("time", []),
        hourly_data.get("relative_humidity_2m", []),
        tz,
        current_time,
        "humidity",
    )
    current_humidity = int(raw_humidity) if raw_humidity != "N/A" else "N/A"
    data_points.append(
        {
            "label": "Humidity",
            "measurement": current_humidity,
            "unit": "%",
            "icon": os.path.join(plugin_dir, "icons/humidity.png"),
        }
    )

    # Pressure
    raw_pressure = _get_current_hourly_value(
        hourly_data.get("time", []),
        hourly_data.get("surface_pressure", []),
        tz,
        current_time,
        "pressure",
    )
    current_pressure = int(raw_pressure) if raw_pressure != "N/A" else "N/A"
    data_points.append(
        {
            "label": "Pressure",
            "measurement": current_pressure,
            "unit": "hPa",
            "icon": os.path.join(plugin_dir, "icons/pressure.png"),
        }
    )

    # UV Index
    current_uv_index = _get_current_hourly_value(
        aqi_data.get("hourly", {}).get("time", []),
        aqi_data.get("hourly", {}).get("uv_index", []),
        tz,
        current_time,
        "UV Index",
    )
    data_points.append(
        {
            "label": "UV Index",
            "measurement": current_uv_index,
            "unit": "",
            "icon": os.path.join(plugin_dir, "icons/uvi.png"),
        }
    )

    # Visibility
    unit_label = "mi" if units == "imperial" else "km"
    raw_visibility = _get_current_hourly_value(
        hourly_data.get("time", []),
        hourly_data.get("visibility", []),
        tz,
        current_time,
        "visibility",
    )
    visibility_str = _format_open_meteo_visibility(raw_visibility, units)
    data_points.append(
        {
            "label": "Visibility",
            "measurement": visibility_str,
            "unit": unit_label,
            "icon": os.path.join(plugin_dir, "icons/visibility.png"),
        }
    )

    # Air Quality
    raw_aqi = _get_current_hourly_value(
        aqi_data.get("hourly", {}).get("time", []),
        aqi_data.get("hourly", {}).get("european_aqi", []),
        tz,
        current_time,
        "AQI",
    )
    current_aqi, scale = _format_open_meteo_aqi(raw_aqi)
    data_points.append(
        {
            "label": "Air Quality",
            "measurement": current_aqi,
            "unit": scale,
            "icon": os.path.join(plugin_dir, "icons/aqi.png"),
        }
    )

    return data_points


def parse_weather_data(weather_data, aqi_data, tz, units, time_format, lat, plugin_dir):
    current = weather_data.get("current", {})
    if not current or current.get("dt") is None:
        raise AttributeError("Missing current weather data.")
    dt = datetime.fromtimestamp(current.get("dt"), tz=UTC).astimezone(tz)
    weather_list = current.get("weather", [])
    if not weather_list:
        raise RuntimeError("Weather data missing 'weather' field")
    current_icon = weather_list[0].get("icon", "01d")
    icon_codes_to_preserve = ["01", "02", "10"]
    icon_code = current_icon[:2]
    current_suffix = current_icon[-1]

    if icon_code not in icon_codes_to_preserve and current_icon.endswith("n"):
        current_icon = current_icon.replace("n", "d")
    data = {
        "current_date": dt.strftime("%A, %B %d"),
        "current_day_icon": os.path.join(plugin_dir, f"{current_icon}.png"),
        "current_temperature": str(round(current.get("temp"))),
        "feels_like": str(round(current.get("feels_like"))),
        "temperature_unit": UNITS[units]["temperature"],
        "units": units,
        "time_format": time_format,
    }
    data["forecast"] = parse_forecast(
        weather_data.get("daily"), tz, current_suffix, lat, plugin_dir
    )
    data["data_points"] = parse_data_points(
        weather_data, aqi_data, tz, units, time_format, plugin_dir
    )

    data["hourly_forecast"] = parse_hourly(
        weather_data.get("hourly"), tz, time_format, units
    )
    return data


def parse_open_meteo_data(
    weather_data, aqi_data, tz, units, time_format, lat, plugin_dir
):
    current = weather_data.get("current_weather", {})
    dt = (
        datetime.fromisoformat(current.get("time")).astimezone(tz)
        if current.get("time")
        else datetime.now(tz)
    )
    weather_code = current.get("weathercode", 0)
    is_day = current.get("is_day", 1)
    current_icon = map_weather_code_to_icon(weather_code, is_day)

    data = {
        "current_date": dt.strftime("%A, %B %d"),
        "current_day_icon": os.path.join(plugin_dir, f"{current_icon}.png"),
        "current_temperature": str(round(current.get("temperature", 0))),
        "feels_like": str(
            round(current.get("apparent_temperature", current.get("temperature", 0)))
        ),
        "temperature_unit": UNITS[units]["temperature"],
        "units": units,
        "time_format": time_format,
    }

    data["forecast"] = parse_open_meteo_forecast(
        weather_data.get("daily", {}), tz, is_day, lat, plugin_dir
    )
    data["data_points"] = parse_open_meteo_data_points(
        weather_data, aqi_data, tz, units, time_format, plugin_dir
    )

    data["hourly_forecast"] = parse_open_meteo_hourly(
        weather_data.get("hourly", {}), tz, time_format
    )
    return data

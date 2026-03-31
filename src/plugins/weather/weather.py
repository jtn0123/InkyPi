import logging
import os
from datetime import datetime

import pytz

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import (
    field,
    option,
    row,
    schema,
    section,
    widget,
)
from plugins.weather import weather_api, weather_data as _wd

logger = logging.getLogger(__name__)


class Weather(BasePlugin):
    def build_settings_schema(self):
        return schema(
            section(
                "Location",
                widget("weather-map", template="widgets/weather_map.html"),
            ),
            section(
                "Data",
                row(
                    field(
                        "weatherProvider",
                        "select",
                        label="Weather Provider",
                        default="OpenMeteo",
                        options=[
                            option("OpenMeteo", "Open-Meteo"),
                            option("OpenWeatherMap", "OpenWeatherMap"),
                        ],
                    ),
                    field(
                        "units",
                        "select",
                        label="Units",
                        default="imperial",
                        options=[
                            option("imperial", "Imperial (°F)"),
                            option("metric", "Metric (°C)"),
                            option("standard", "Standard (K)"),
                        ],
                    ),
                    field(
                        "weatherTimeZone",
                        "select",
                        label="Time Zone",
                        default="locationTimeZone",
                        options=[
                            option("locationTimeZone", "Use Location Time Zone"),
                            option("localTimeZone", "Use Local Time Zone"),
                        ],
                        visible_if={
                            "field": "weatherProvider",
                            "equals": "OpenWeatherMap",
                        },
                    ),
                ),
            ),
            section(
                "Title",
                row(
                    field(
                        "titleSelection",
                        "radio_segment",
                        label="Title Source",
                        default="location",
                        options=[
                            option("location", "Location"),
                            option("custom", "Custom"),
                        ],
                        visible_if={
                            "field": "weatherProvider",
                            "equals": "OpenWeatherMap",
                        },
                    ),
                    field(
                        "customTitle",
                        label="Custom Title",
                        placeholder="Custom forecast title",
                        visible_if={"field": "titleSelection", "equals": "custom"},
                    ),
                ),
            ),
            section(
                "Display",
                row(
                    field(
                        "displayRefreshTime",
                        "checkbox",
                        label="Refresh Time",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                    field(
                        "displayMetrics",
                        "checkbox",
                        label="Metrics",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                    field(
                        "displayGraph",
                        "checkbox",
                        label="Weather Graph",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                ),
                row(
                    field(
                        "displayRain",
                        "checkbox",
                        label="Rain Amount",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                    field(
                        "moonPhase",
                        "checkbox",
                        label="Moon Phase",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                ),
                row(
                    field(
                        "displayGraphIcons",
                        "checkbox",
                        label="Graph Icons",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                    field(
                        "graphIconStep",
                        "select",
                        label="Graph Icon Interval",
                        default="2",
                        options=[
                            option("1", "Every 1 hour"),
                            option("2", "Every 2 hours"),
                            option("4", "Every 4 hours"),
                            option("6", "Every 6 hours"),
                            option("12", "Every 12 hours"),
                        ],
                        visible_if={"field": "displayGraphIcons", "equals": "true"},
                    ),
                ),
                row(
                    field(
                        "displayForecast",
                        "checkbox",
                        label="Forecast",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                    field(
                        "forecastDays",
                        "select",
                        label="Forecast Days",
                        default="5",
                        options=[
                            option("3", "3 days"),
                            option("5", "5 days"),
                            option("7", "7 days"),
                        ],
                        visible_if={"field": "displayForecast", "equals": "true"},
                    ),
                ),
            ),
        )

    def _request_timeout(self) -> float:
        try:
            return float(os.getenv("INKYPI_HTTP_TIMEOUT_DEFAULT_S", "20"))
        except (ValueError, TypeError):
            return 20.0

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "OpenWeatherMap",
            "expected_key": "OPEN_WEATHER_MAP_SECRET",
        }
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        lat_str = settings.get("latitude")
        long_str = settings.get("longitude")
        if not lat_str or not long_str:
            raise RuntimeError("Latitude and longitude are required.")
        try:
            lat = float(lat_str)
            long = float(long_str)
        except (ValueError, TypeError):
            raise RuntimeError(
                "Latitude and longitude must be valid numbers."
            ) from None

        units = settings.get("units")
        if not units or units not in ["metric", "imperial", "standard"]:
            raise RuntimeError("Units are required.")

        weather_provider = settings.get("weatherProvider", "OpenWeatherMap")
        title = settings.get("customTitle", "")

        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)
        self._request_timeout()
        self.get_plugin_dir()

        try:
            if weather_provider == "OpenWeatherMap":
                api_key = device_config.load_env_key("OPEN_WEATHER_MAP_SECRET")
                if not api_key:
                    logger.error("OpenWeatherMap API Key not configured")
                    raise RuntimeError("OpenWeatherMap API Key not configured.")
                weather_data = self.get_weather_data(api_key, units, lat, long)
                aqi_data = self.get_air_quality(api_key, lat, long)
                if settings.get("titleSelection", "location") == "location":
                    title = self.get_location(api_key, lat, long)
                if (
                    settings.get("weatherTimeZone", "locationTimeZone")
                    == "locationTimeZone"
                ):
                    logger.info("Using location timezone for OpenWeatherMap data.")
                    wtz = self.parse_timezone(weather_data)
                    template_params = self.parse_weather_data(
                        weather_data, aqi_data, wtz, units, time_format, lat
                    )
                else:
                    logger.info("Using configured timezone for OpenWeatherMap data.")
                    template_params = self.parse_weather_data(
                        weather_data, aqi_data, tz, units, time_format, lat
                    )
            elif weather_provider == "OpenMeteo":
                forecast_days = 7
                weather_data = self.get_open_meteo_data(
                    lat, long, units, forecast_days + 1
                )
                aqi_data = self.get_open_meteo_air_quality(lat, long)
                template_params = self.parse_open_meteo_data(
                    weather_data, aqi_data, tz, units, time_format, lat
                )
            else:
                raise RuntimeError(f"Unknown weather provider: {weather_provider}")

            template_params["title"] = title
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"{weather_provider} request failed: {str(e)}")
            raise RuntimeError(
                f"{weather_provider} request failure, please check logs."
            ) from e

        dimensions = self.get_oriented_dimensions(device_config)

        template_params["plugin_settings"] = settings

        # Add last refresh time
        now = datetime.now(tz)
        if time_format == "24h":
            last_refresh_time = now.strftime("%Y-%m-%d %H:%M")
        else:
            last_refresh_time = now.strftime("%Y-%m-%d %I:%M %p")
        template_params["last_refresh_time"] = last_refresh_time

        image = self.render_image(
            dimensions, "weather.html", "weather.css", template_params
        )

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image

    # Delegate methods — keep backward compatibility for tests and external callers
    def get_weather_data(self, api_key, units, lat, long):
        return weather_api.get_weather_data(
            api_key, units, lat, long, self._request_timeout()
        )

    def get_air_quality(self, api_key, lat, long):
        return weather_api.get_air_quality(api_key, lat, long, self._request_timeout())

    def get_location(self, api_key, lat, long):
        return weather_api.get_location(api_key, lat, long, self._request_timeout())

    def get_open_meteo_data(self, lat, long, units, forecast_days):
        return weather_api.get_open_meteo_data(
            lat, long, units, forecast_days, self._request_timeout()
        )

    def get_open_meteo_air_quality(self, lat, long):
        return weather_api.get_open_meteo_air_quality(
            lat, long, self._request_timeout()
        )

    def format_time(self, dt, time_format, hour_only=False, include_am_pm=True):
        return _wd.format_time(dt, time_format, hour_only, include_am_pm)

    def get_wind_arrow(self, wind_deg):
        return _wd.get_wind_arrow(wind_deg)

    def parse_timezone(self, weatherdata):
        return _wd.parse_timezone(weatherdata)

    def map_weather_code_to_icon(self, weather_code, is_day):
        return _wd.map_weather_code_to_icon(weather_code, is_day)

    def get_moon_phase_icon_path(self, phase_name, lat):
        return _wd.get_moon_phase_icon_path(phase_name, lat, self.get_plugin_dir())

    def parse_forecast(self, daily_forecast, tz, current_suffix, lat):
        return _wd.parse_forecast(
            daily_forecast, tz, current_suffix, lat, self.get_plugin_dir()
        )

    def parse_open_meteo_forecast(self, daily_data, tz, is_day, lat):
        return _wd.parse_open_meteo_forecast(
            daily_data, tz, is_day, lat, self.get_plugin_dir()
        )

    def parse_hourly(self, hourly_forecast, tz, time_format, units):
        return _wd.parse_hourly(hourly_forecast, tz, time_format, units)

    def parse_open_meteo_hourly(self, hourly_data, tz, time_format):
        return _wd.parse_open_meteo_hourly(hourly_data, tz, time_format)

    def parse_data_points(self, weather, air_quality, tz, units, time_format):
        return _wd.parse_data_points(
            weather, air_quality, tz, units, time_format, self.get_plugin_dir()
        )

    def parse_open_meteo_data_points(
        self, weather_data, aqi_data, tz, units, time_format
    ):
        return _wd.parse_open_meteo_data_points(
            weather_data, aqi_data, tz, units, time_format, self.get_plugin_dir()
        )

    def parse_weather_data(self, weather_data, aqi_data, tz, units, time_format, lat):
        return _wd.parse_weather_data(
            weather_data, aqi_data, tz, units, time_format, lat, self.get_plugin_dir()
        )

    def parse_open_meteo_data(
        self, weather_data, aqi_data, tz, units, time_format, lat
    ):
        return _wd.parse_open_meteo_data(
            weather_data, aqi_data, tz, units, time_format, lat, self.get_plugin_dir()
        )

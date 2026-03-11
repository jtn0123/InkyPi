"""
APOD Plugin for InkyPi
This plugin fetches the Astronomy Picture of the Day (APOD) from NASA's API
and displays it on the InkyPi device. It supports optional manual date selection or random dates.
For the API key, set `NASA_SECRET={API_KEY}` in your .env file.
"""

import logging
import os
from datetime import datetime, timedelta
from io import BytesIO
from random import randint

import requests
from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, field, schema, section

logger = logging.getLogger(__name__)

class Apod(BasePlugin):
    def build_settings_schema(self):
        today = datetime.today().strftime("%Y-%m-%d")
        return schema(
            section(
                "Source",
                callout(
                    "Pick a specific APOD date or enable randomization to explore past entries from NASA's archive.",
                    title="NASA APOD",
                ),
                field(
                    "randomizeApod",
                    "checkbox",
                    label="Randomize Date",
                    hint="When enabled, InkyPi chooses a random APOD date instead of using the date field below.",
                    submit_unchecked=True,
                    checked_value="true",
                    unchecked_value="false",
                ),
                field(
                    "customDate",
                    "date",
                    label="Date",
                    default=today,
                    visible_if={"field": "randomizeApod", "equals": "false"},
                ),
            )
        )

    def _request_timeout(self) -> float:
        try:
            return float(os.getenv("INKYPI_HTTP_TIMEOUT_DEFAULT_S", "20"))
        except Exception:
            return 20.0

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "NASA",
            "expected_key": "NASA_SECRET"
        }
        template_params['style_settings'] = False
        return template_params

    def generate_image(self, settings, device_config):
        logger.info(f"APOD plugin settings: {settings}")

        api_key = device_config.load_env_key("NASA_SECRET")
        if not api_key:
            logger.error("NASA API Key not configured")
            raise RuntimeError("NASA API Key not configured.")

        params = {"api_key": api_key}

        if settings.get("randomizeApod") == "true":
            start = datetime(2015, 1, 1)
            end = datetime.today()
            delta_days = (end - start).days
            random_date = start + timedelta(days=randint(0, delta_days))
            params["date"] = random_date.strftime("%Y-%m-%d")
        elif settings.get("customDate"):
            params["date"] = settings["customDate"]

        response = requests.get(
            "https://api.nasa.gov/planetary/apod",
            params=params,
            timeout=self._request_timeout(),
        )

        if response.status_code != 200:
            logger.error(f"NASA API error: {response.text}")
            raise RuntimeError("Failed to retrieve NASA APOD.")

        data = response.json()

        if data.get("media_type") != "image":
            raise RuntimeError("APOD is not an image today.")

        image_url = data.get("hdurl") or data.get("url")

        try:
            img_data = requests.get(image_url, timeout=self._request_timeout())
            if not 200 <= img_data.status_code < 300:
                logger.error(f"Failed to fetch APOD image: status {img_data.status_code}")
                raise RuntimeError("Failed to fetch APOD image.")
            with Image.open(BytesIO(img_data.content)) as img:
                image = img.copy()
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Failed to load APOD image: {str(e)}")
            raise RuntimeError("Failed to load APOD image.")

        return image

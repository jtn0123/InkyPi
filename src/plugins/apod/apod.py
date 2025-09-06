"""
APOD Plugin for InkyPi
This plugin fetches the Astronomy Picture of the Day (APOD) from NASA's API
and displays it on the InkyPi device. It supports optional manual date selection or random dates.
For the API key, set `NASA_SECRET={API_KEY}` in your .env file.
"""

import logging
from datetime import datetime, timedelta
from io import BytesIO
from random import randint

import requests
from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_utils import http_get

logger = logging.getLogger(__name__)


class Apod(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "NASA",
            "expected_key": "NASA_SECRET",
        }
        template_params["style_settings"] = False
        return template_params

    def generate_image(self, settings, device_config):
        logger.info(f"APOD plugin settings: {settings}")

        api_key = device_config.load_env_key("NASA_SECRET")
        if not api_key:
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

        try:
            response = http_get(
                "https://api.nasa.gov/planetary/apod", params=params, timeout=15
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"NASA API error: {str(e)}")
            raise RuntimeError("Failed to retrieve NASA APOD.")

        data = response.json()

        if data.get("media_type") != "image":
            raise RuntimeError("APOD is not an image today.")

        image_url = data.get("hdurl") or data.get("url")

        try:
            img_data = http_get(image_url, timeout=30)
            img_data.raise_for_status()
            with Image.open(BytesIO(img_data.content)) as _img:
                image = _img.copy()
        except Exception as e:
            logger.error(f"Failed to load APOD image: {str(e)}")
            raise RuntimeError("Failed to load APOD image.")

        return image

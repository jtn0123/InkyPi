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
from utils.image_utils import load_image_from_bytes
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

        # Ask NASA for thumbnails on non-image days (e.g., YouTube videos)
        # See https://api.nasa.gov/ for APOD 'thumbs' parameter
        params = {"api_key": api_key, "thumbs": True}

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
            if getattr(response, "status_code", 200) >= 400:
                raise RuntimeError("Failed to retrieve NASA APOD.")
        except Exception as e:
            logger.error(f"NASA API error: {str(e)}")
            raise RuntimeError("Failed to retrieve NASA APOD.")

        data = response.json()

        # On image days, prefer HD URL; on video days, fall back to thumbnail if present
        if data.get("media_type") == "image":
            image_url = data.get("hdurl") or data.get("url")
        else:
            image_url = data.get("thumbnail_url")
            if not image_url:
                # No thumbnail available; surface a clear error
                raise RuntimeError("APOD is not an image today.")

        try:
            try:
                img_data = http_get(image_url, timeout=30)
            except TypeError:
                img_data = http_get(image_url)
            if getattr(img_data, "status_code", 200) not in (200, 201, 204):
                raise requests.exceptions.HTTPError(
                    str(getattr(img_data, "status_code", 0))
                )
            # Primary path: centralized loader
            image = load_image_from_bytes(img_data.content, image_open=Image.open)
            if image is None:
                raise RuntimeError("Failed to decode APOD image bytes")
        except Exception as e:
            logger.error(f"Failed to load APOD image: {str(e)}")
            raise RuntimeError("Failed to load APOD image.")

        return image

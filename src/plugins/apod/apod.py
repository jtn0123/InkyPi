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
from utils.progress import record_step
from time import perf_counter

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
            _t_api = perf_counter()
            response = http_get(
                "https://api.nasa.gov/planetary/apod", params=params, timeout=15
            )
            if getattr(response, "status_code", 200) >= 400:
                raise RuntimeError("Failed to retrieve NASA APOD.")
            try:
                record_step("provider_api")
            except Exception:
                pass
            try:
                logger.info("APOD API elapsed_ms=%s", int((perf_counter() - _t_api) * 1000))
            except Exception:
                pass
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
                _t_dl = perf_counter()
                img_data = http_get(image_url, timeout=30)
            except TypeError:
                _t_dl = perf_counter()
                img_data = http_get(image_url)
            if getattr(img_data, "status_code", 200) not in (200, 201, 204):
                raise requests.exceptions.HTTPError(
                    str(getattr(img_data, "status_code", 0))
                )
            # Primary path: centralized loader
            content = img_data.content
            try:
                record_step("provider_download")
            except Exception:
                pass
            try:
                logger.info("APOD image download elapsed_ms=%s bytes=%s", int((perf_counter() - _t_dl) * 1000), len(content))
            except Exception:
                pass

            _t_dec = perf_counter()
            image = load_image_from_bytes(content, image_open=Image.open)
            if image is None:
                raise RuntimeError("Failed to decode APOD image bytes")
            try:
                record_step("provider_decode")
            except Exception:
                pass
            try:
                logger.info("APOD image decode elapsed_ms=%s", int((perf_counter() - _t_dec) * 1000))
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to load APOD image: {str(e)}")
            raise RuntimeError("Failed to load APOD image.")

        # Surface metadata for the web UI similar to WPOTD
        try:
            apod_date = data.get("date")  # YYYY-MM-DD
            title = data.get("title")
            explanation = data.get("explanation")
            # Build canonical APOD page URL when possible: apYYMMDD.html
            page_url = None
            if isinstance(apod_date, str) and len(apod_date) == 10:
                try:
                    y, m, d = apod_date.split("-")
                    page_url = f"https://apod.nasa.gov/apod/ap{y[2:]}{m}{d}.html"
                except Exception:
                    page_url = None

            plugin_meta = {
                "date": apod_date,
                "title": title,
                "explanation": explanation,
                "media_type": data.get("media_type"),
                "image_url": image_url,
                "page_url": page_url,
                "copyright": data.get("copyright"),
            }
            self.set_latest_metadata(plugin_meta)
        except Exception:
            # Never fail render due to metadata enrichment
            pass

        return image

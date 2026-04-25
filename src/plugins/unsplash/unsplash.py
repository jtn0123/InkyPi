import logging
import os
import secrets
from collections.abc import Mapping
from typing import Any, cast

from PIL import Image
from requests.exceptions import RequestException

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import (
    callout,
    field,
    option,
    row,
    schema,
    section,
)
from utils.http_client import get_http_session
from utils.image_utils import fetch_and_resize_remote_image

logger = logging.getLogger(__name__)


def grab_image(
    image_url: str, dimensions: tuple[int, int], timeout_ms: int = 40000
) -> Image.Image | None:
    """Grab an image from a URL and resize it to the specified dimensions."""
    return fetch_and_resize_remote_image(
        image_url, dimensions, timeout_seconds=timeout_ms / 1000
    )


class Unsplash(BasePlugin):
    def build_settings_schema(self) -> dict[str, object]:
        return schema(
            section(
                "Search",
                callout(
                    "Leave the search query blank to fetch a random image, or add a query and collections to narrow the selection.",
                    title="Unsplash Source",
                ),
                field(
                    "search_query",
                    label="Search Query",
                    placeholder="mountains at sunrise",
                    hint="Optional. If blank, InkyPi fetches a random image.",
                ),
                field(
                    "collections",
                    label="Collections",
                    placeholder="1234,5678",
                    hint="Optional. Use comma-separated Unsplash collection IDs.",
                ),
            ),
            section(
                "Filters",
                row(
                    field(
                        "content_filter",
                        "select",
                        label="Content Filter",
                        default="low",
                        options=[
                            option("low", "Avoid nudity and violence"),
                            option("high", "No filtering"),
                        ],
                    ),
                    field(
                        "color",
                        "select",
                        label="Color",
                        default="",
                        options=[
                            option("", "Any"),
                            option("black_and_white", "Black and White"),
                            option("black", "Black"),
                            option("white", "White"),
                            option("yellow", "Yellow"),
                            option("orange", "Orange"),
                            option("red", "Red"),
                            option("purple", "Purple"),
                            option("magenta", "Magenta"),
                            option("green", "Green"),
                            option("teal", "Teal"),
                            option("blue", "Blue"),
                        ],
                    ),
                    field(
                        "orientation",
                        "select",
                        label="Orientation",
                        default="",
                        options=[
                            option("", "Any"),
                            option("landscape", "Landscape"),
                            option("portrait", "Portrait"),
                        ],
                    ),
                ),
            ),
        )

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "Unsplash",
            "expected_key": "UNSPLASH_ACCESS_KEY",
        }
        return template_params

    def _request_timeout(self) -> float:
        try:
            return float(os.getenv("INKYPI_HTTP_TIMEOUT_DEFAULT_S", "20"))
        except (ValueError, TypeError):
            return 20.0

    def generate_image(
        self, settings: Mapping[str, object], device_config: DeviceConfigLike
    ) -> Image.Image:
        access_key = device_config.load_env_key("UNSPLASH_ACCESS_KEY")
        if not access_key:
            logger.error("Unsplash API Key not configured")
            raise RuntimeError("Unsplash API Key not configured.")

        search_query = settings.get("search_query")
        if not isinstance(search_query, str):
            search_query = None

        collections = settings.get("collections")
        if not isinstance(collections, str):
            collections = None

        content_filter = settings.get("content_filter", "low")
        if not isinstance(content_filter, str):
            content_filter = "low"

        color = settings.get("color")
        if not isinstance(color, str):
            color = None

        orientation = settings.get("orientation")
        if not isinstance(orientation, str):
            orientation = None

        params: dict[str, object] = {
            "client_id": access_key,
            "content_filter": content_filter,
            "per_page": 100,
        }

        unsplash_base = os.getenv("INKYPI_UNSPLASH_API_URL", "https://api.unsplash.com")
        if search_query:
            url = f"{unsplash_base}/search/photos"
            params["query"] = search_query
        else:
            url = f"{unsplash_base}/photos/random"

        if collections:
            params["collections"] = collections
        if color:
            params["color"] = color
        if orientation:
            params["orientation"] = orientation

        try:
            response = get_http_session().get(
                url, params=cast(Any, params), timeout=self._request_timeout()
            )
            response.raise_for_status()
            data = cast(dict[str, object], response.json())
            if search_query:
                results = data.get("results")
                if not isinstance(results, list):
                    results = []
                if not results:
                    raise RuntimeError("No images found for the given search query.")
                first_result = secrets.choice(cast(list[dict[str, object]], results))
                urls = first_result.get("urls")
                if not isinstance(urls, dict):
                    raise KeyError("urls")
                image_url = cast(str, urls["full"])
            else:
                urls = data.get("urls")
                if not isinstance(urls, dict):
                    raise KeyError("urls")
                image_url = cast(str, urls["full"])
        except RequestException as e:
            logger.error(f"Error fetching image from Unsplash API: {e}")
            raise RuntimeError(
                "Failed to fetch image from Unsplash API, please check logs."
            ) from e
        except (KeyError, IndexError) as e:
            logger.error(f"Error parsing Unsplash API response: {e}")
            raise RuntimeError(
                "Failed to parse Unsplash API response, please check logs."
            ) from e

        dimensions = self.get_oriented_dimensions(device_config)

        logger.info(f"Grabbing image from: {image_url}")

        image = grab_image(image_url, dimensions, timeout_ms=40000)

        if not image:
            raise RuntimeError("Failed to load image, please check logs.")

        return image

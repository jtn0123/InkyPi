import logging
import os
from collections.abc import Mapping
from typing import Any, cast

from PIL import Image

from utils.http_client import get_http_session

logger = logging.getLogger(__name__)


def stars_generate_image(
    plugin_instance: Any, settings: Mapping[str, object], device_config: Any
) -> Image.Image:
    raw_username = settings.get("githubUsername")
    raw_repository = settings.get("githubRepository")
    username = raw_username if isinstance(raw_username, str) else ""
    repository = raw_repository if isinstance(raw_repository, str) else ""

    if not username or not repository:
        raise RuntimeError("GitHub username and repository are required.")

    dimensions = plugin_instance.get_oriented_dimensions(device_config)

    github_repository = repository if "/" in repository else username + "/" + repository

    try:
        stars = fetch_stars(github_repository)
    except Exception as e:
        logger.error(f"GitHub graphql request failed: {str(e)}")
        raise RuntimeError("GitHub request failure, please check logs") from e

    template_params = {
        "repository": github_repository,
        "stars": stars,
        "plugin_settings": settings,
    }

    return plugin_instance.render_image(
        dimensions, "github_stars.html", "github.css", template_params
    )


_GITHUB_API_BASE = os.getenv("INKYPI_GITHUB_API_URL", "https://api.github.com")


def fetch_stars(github_repository: str) -> int:
    url = f"{_GITHUB_API_BASE}/repos/{github_repository}"
    headers = {"Accept": "application/json"}

    response = get_http_session().get(url, headers=headers, timeout=30)
    if response.status_code != 200:
        logger.error(
            "GitHub Stars Plugin: Error: %s - %s",
            response.status_code,
            response.text,
        )
        return 0
    try:
        data = cast(dict[str, Any], response.json())
    except ValueError as e:
        logger.error("GitHub Stars Plugin: Invalid JSON response: %s", e)
        return 0
    return int(data.get("stargazers_count", 0) or 0)

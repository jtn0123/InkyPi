import logging

from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

def stars_generate_image(plugin_instance, settings, device_config):
    username = settings.get('githubUsername')
    repository = settings.get('githubRepository')

    if not username or not repository:
        raise RuntimeError("GitHub username and repository are required.")

    dimensions = plugin_instance.get_oriented_dimensions(device_config)

    github_repository = username + "/" + repository

    try:
        stars = fetch_stars(github_repository)
    except Exception as e:
        logger.error(f"GitHub graphql request failed: {str(e)}")
        raise RuntimeError("GitHub request failure, please check logs")

    template_params = {
        "repository": github_repository,
        "stars": stars,
        "plugin_settings": settings
    }

    return plugin_instance.render_image(
        dimensions,
        "github_stars.html",
        "github.css",
        template_params
    )

def fetch_stars(github_repository):
    url = f"https://api.github.com/repos/{github_repository}"
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
        data = response.json()
    except ValueError as e:
        logger.error("GitHub Stars Plugin: Invalid JSON response: %s", e)
        return 0
    return int(data.get('stargazers_count', 0) or 0)

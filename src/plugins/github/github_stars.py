import logging
import requests

logger = logging.getLogger(__name__)

def stars_generate_image(plugin_instance, settings, device_config):
    username = settings.get('githubUsername')
    repository = settings.get('githubRepository')

    if not username or not repository:
        raise RuntimeError("GitHub username and repository are required.")

    dimensions = device_config.get_resolution()
    if device_config.get_config("orientation") == "vertical":
        dimensions = dimensions[::-1]

    github_repository = username + "/" + repository

    try:
        stars = fetch_stars(github_repository)
    except Exception as e:
        logger.error(f"GitHub graphql request failed: {str(e)}")
        raise RuntimeError(f"GitHub request failure, please check logs")

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

    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        data = response.json()
    else:
        logger.error(f"GitHub Stars Plugin: Error: {response.status_code} - {response.text}")
        raise RuntimeError(f"GitHub API error: {response.status_code}")

    data = response.json()
    return data['stargazers_count']


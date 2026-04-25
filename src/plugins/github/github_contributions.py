import logging
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from PIL import Image

from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

GRAPHQL_QUERY = """
query($username: String!) {
  user(login: $username) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""


def contributions_generate_image(
    plugin_instance: Any, settings: Mapping[str, object], device_config: Any
) -> Image.Image:
    dimensions = plugin_instance.get_oriented_dimensions(device_config)

    api_key = device_config.load_env_key("GITHUB_SECRET")
    if not api_key:
        logger.error("GitHub API Key not configured")
        raise RuntimeError("GitHub API Key not configured.")

    raw_colors = settings.get("contributionColor[]")
    colors = (
        raw_colors
        if isinstance(raw_colors, list)
        else [
            "#ebedf0",
            "#9be9a8",
            "#40c463",
            "#30a14e",
            "#216e39",
        ]
    )
    colors = [color for color in colors if isinstance(color, str)]
    raw_username = settings.get("githubUsername")
    github_username = raw_username if isinstance(raw_username, str) else ""
    if not github_username:
        raise RuntimeError("GitHub username is required.")

    data = fetch_contributions(github_username, api_key)
    grid, month_positions = parse_contributions(data, colors)
    metrics = calculate_metrics(data)

    template_params = {
        "username": github_username,
        "grid": grid,
        "month_positions": month_positions,
        "metrics": metrics,
        "plugin_settings": settings,
    }

    return plugin_instance.render_image(
        dimensions, "github_contributions.html", "github.css", template_params
    )


# -------------------------
# Helper functions
# -------------------------


_GITHUB_API_BASE = os.getenv("INKYPI_GITHUB_API_URL", "https://api.github.com")


def fetch_contributions(username: str, api_key: str) -> dict[str, Any]:
    url = f"{_GITHUB_API_BASE}/graphql"
    headers = {"Authorization": f"Bearer {api_key}"}
    variables = {"username": username}
    resp = get_http_session().post(
        url,
        json={"query": GRAPHQL_QUERY, "variables": variables},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return cast(dict[str, Any], resp.json())


def parse_contributions(
    data: Mapping[str, Any], colors: Sequence[str]
) -> tuple[list[list[dict[str, Any]]], list[dict[str, object]]]:
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"][
        "weeks"
    ]

    grid = [list(week["contributionDays"]) for week in weeks]
    max_contrib = max(day["contributionCount"] for week in grid for day in week)

    def get_color(count: int) -> str:
        if max_contrib == 0 or count == 0:
            return colors[0]
        level = int((count / max_contrib) * (len(colors) - 1))
        return colors[max(1, level)]

    for week in grid:
        for day in week:
            day["color"] = get_color(day["contributionCount"])

    month_positions: list[dict[str, object]] = []
    seen_months: set[str] = set()
    for i, week in enumerate(weeks):
        first_day = week["contributionDays"][0]["date"]
        # Only month/year labels are extracted; tz is irrelevant for formatting.
        dt = datetime.strptime(first_day, "%Y-%m-%d")  # noqa: DTZ007
        month_year = f"{dt.strftime('%b')}-{dt.year}"
        if month_year not in seen_months:
            month_positions.append({"name": dt.strftime("%b"), "index": i})
            seen_months.add(month_year)

    if month_positions:
        month_positions.pop(0)

    return grid, month_positions


def calculate_metrics(data: Mapping[str, Any]) -> list[dict[str, object]]:
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"][
        "weeks"
    ]
    days = [day for week in weeks for day in week["contributionDays"]]
    days = sorted(days, key=lambda d: d["date"])

    total = sum(day["contributionCount"] for day in days)
    streak, longest_streak, current_streak = 0, 0, 0
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    in_current_streak = False

    for day in days:
        day_date = date.fromisoformat(day["date"])
        if day["contributionCount"] > 0:
            streak += 1
            longest_streak = max(longest_streak, streak)
            if day_date in (today, yesterday) or in_current_streak:
                current_streak = streak
                in_current_streak = True
        else:
            streak = 0
            in_current_streak = False

    return [
        {"title": "Contributions", "value": total},
        {"title": "Current Streak", "value": current_streak},
        {"title": "Longest Streak", "value": longest_streak},
    ]

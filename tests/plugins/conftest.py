# pyright: reportMissingImports=false
"""Shared fixtures with realistic API response shapes for plugin tests."""

from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image


@pytest.fixture()
def realistic_weather_response():
    """Return a dict matching the actual OpenWeatherMap One Call API shape."""
    return {
        "lat": 40.7128,
        "lon": -74.006,
        "timezone": "America/New_York",
        "timezone_offset": -18000,
        "current": {
            "dt": 1710700000,
            "sunrise": 1710672000,
            "sunset": 1710714000,
            "temp": 12.5,
            "feels_like": 10.8,
            "pressure": 1013,
            "humidity": 65,
            "dew_point": 6.1,
            "uvi": 3.2,
            "clouds": 40,
            "visibility": 10000,
            "wind_speed": 5.1,
            "wind_deg": 220,
            "weather": [
                {
                    "id": 802,
                    "main": "Clouds",
                    "description": "scattered clouds",
                    "icon": "03d",
                }
            ],
        },
        "daily": [
            {
                "dt": 1710691200,
                "sunrise": 1710672000,
                "sunset": 1710714000,
                "temp": {
                    "day": 12.5,
                    "min": 5.2,
                    "max": 14.8,
                    "night": 7.1,
                    "eve": 11.0,
                    "morn": 5.8,
                },
                "feels_like": {"day": 10.8, "night": 5.3, "eve": 9.4, "morn": 3.2},
                "pressure": 1013,
                "humidity": 65,
                "weather": [
                    {
                        "id": 802,
                        "main": "Clouds",
                        "description": "scattered clouds",
                        "icon": "03d",
                    }
                ],
                "wind_speed": 5.1,
                "wind_deg": 220,
                "pop": 0.2,
            }
        ]
        * 7,
        "hourly": [
            {
                "dt": 1710700000 + i * 3600,
                "temp": 12.5 + i * 0.3,
                "feels_like": 10.8 + i * 0.2,
                "pressure": 1013,
                "humidity": 65 - i,
                "weather": [
                    {
                        "id": 802,
                        "main": "Clouds",
                        "description": "scattered clouds",
                        "icon": "03d",
                    }
                ],
                "pop": 0.1,
                "wind_speed": 5.1,
            }
            for i in range(24)
        ],
    }


@pytest.fixture()
def realistic_rss_feed():
    """Return a feedparser-compatible feed object matching a real RSS feed shape."""
    feed = MagicMock()
    feed.bozo = False
    feed.feed.title = "Example News"
    feed.feed.link = "https://example.com"

    entries = []
    for i in range(5):
        entry = MagicMock()
        entry.title = f"Article {i + 1}: Breaking News Story"
        entry.link = f"https://example.com/article-{i + 1}"
        entry.description = (
            f"<p>This is the summary of article {i + 1}. "
            f'<img src="https://example.com/images/article-{i + 1}.jpg" alt="Article image" /> '
            f"It contains <b>HTML formatting</b> and &amp; entities.</p>"
        )
        entry.published = "Mon, 18 Mar 2026 12:00:00 GMT"
        entry.published_parsed = (2026, 3, 18, 12, 0, 0, 0, 77, 0)
        entry.get = lambda key, default=None, _e=entry: getattr(_e, key, default)
        entries.append(entry)

    feed.entries = entries
    return feed


@pytest.fixture()
def realistic_nasa_apod_response():
    """Return a dict matching the actual NASA APOD API response shape."""
    return {
        "date": "2026-03-18",
        "explanation": (
            "What does the center of our galaxy look like? In visible light, "
            "the Milky Way's center is hidden by clouds of obscuring dust and gas."
        ),
        "hdurl": "https://apod.nasa.gov/apod/image/2603/MilkyWayCenter_hd.jpg",
        "media_type": "image",
        "service_version": "v1",
        "title": "The Center of the Milky Way",
        "url": "https://apod.nasa.gov/apod/image/2603/MilkyWayCenter.jpg",
        "copyright": "NASA/ESA",
    }


@pytest.fixture()
def fake_image_response():
    """Return a mock HTTP response containing a small valid PNG image."""
    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    resp = MagicMock()
    resp.status_code = 200
    resp.content = buf.getvalue()
    resp.headers = {"Content-Type": "image/png"}
    return resp

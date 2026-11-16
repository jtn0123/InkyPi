"""APOD keeps each picture it found on disk, keyed by date (G11).

A fixed-date instance asked the API, read the website and downloaded the same
picture on every turn: 30 times a day on the owner's Pi. Now a date already
shown is answered from the cache with no request at all. Today's picture is
cached once NASA has published it, and random mode is never cached.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image

import plugins.apod.apod as apod_mod
from plugins.apod.apod import Apod

TODAY = date(2026, 11, 16)


def _answer(day: str) -> dict[str, Any]:
    return {
        "date": day,
        "media_type": "image",
        "title": f"Picture of {day}",
        "explanation": "Stars.",
        "url": f"https://apod.nasa.gov/apod/image/{day}.jpg",
    }


class _Nasa:
    """Answers the APOD API for whatever date is asked; counts requests."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.today = TODAY.isoformat()
        self.requests = 0
        session = MagicMock()
        session.get.side_effect = self._get
        monkeypatch.setattr(apod_mod, "get_http_session", lambda: session)
        monkeypatch.setattr(apod_mod, "_apod_today", lambda: TODAY)

    def _get(self, url: str, params: dict[str, str], **_kwargs: Any) -> Any:
        self.requests += 1
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _answer(params.get("date", self.today))
        return response


def _plugin(
    monkeypatch: pytest.MonkeyPatch, device_config: Any
) -> tuple[Apod, MagicMock]:
    monkeypatch.setattr(device_config, "load_env_key", lambda key: "test_key")
    plugin = Apod({"id": "apod"})
    downloads = MagicMock(
        side_effect=lambda url, **kw: Image.new("RGB", kw["dimensions"], "navy")
    )
    monkeypatch.setattr(plugin.image_loader, "from_url", downloads)
    return plugin, downloads


def _cache_files(device_config: Any) -> list[str]:
    directory = Path(device_config.plugin_image_dir) / "apod_cache"
    if not directory.is_dir():
        return []
    return sorted(name for name in os.listdir(directory) if not name.startswith("."))


def test_a_fixed_date_is_fetched_once(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    nasa = _Nasa(monkeypatch)
    plugin, downloads = _plugin(monkeypatch, device_config_dev)
    settings = {"randomizeApod": "false", "customDate": "2024-03-18"}

    first = plugin.generate_image(settings, device_config_dev)
    first_meta = plugin.get_latest_metadata()
    plugin.set_latest_metadata(None)
    second = plugin.generate_image(settings, device_config_dev)

    assert nasa.requests == 1
    assert downloads.call_count == 1
    assert second.tobytes() == first.tobytes()
    assert plugin.get_latest_metadata() == first_meta
    assert first_meta is not None and first_meta["title"] == "Picture of 2024-03-18"


def test_todays_picture_is_reused_until_the_date_changes(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    nasa = _Nasa(monkeypatch)
    plugin, downloads = _plugin(monkeypatch, device_config_dev)

    plugin.generate_image({}, device_config_dev)
    plugin.generate_image({}, device_config_dev)
    assert nasa.requests == 1

    tomorrow = date(2026, 11, 17)
    nasa.today = tomorrow.isoformat()
    monkeypatch.setattr(apod_mod, "_apod_today", lambda: tomorrow)
    plugin.generate_image({}, device_config_dev)

    assert nasa.requests == 2
    assert downloads.call_count == 2
    assert plugin.get_latest_metadata()["date"] == "2026-11-17"  # type: ignore[index]


def test_today_is_not_cached_before_nasa_publishes_it(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    nasa = _Nasa(monkeypatch)
    # Just after midnight Eastern the newest picture is still yesterday's.
    nasa.today = "2026-11-15"
    plugin, _downloads = _plugin(monkeypatch, device_config_dev)

    plugin.generate_image({}, device_config_dev)
    plugin.generate_image({}, device_config_dev)

    assert nasa.requests == 2
    assert _cache_files(device_config_dev) == []


def test_random_mode_always_fetches(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    nasa = _Nasa(monkeypatch)
    plugin, downloads = _plugin(monkeypatch, device_config_dev)
    monkeypatch.setattr(apod_mod, "randint", lambda _a, _b: 100)
    settings = {"randomizeApod": "true"}

    plugin.generate_image(settings, device_config_dev)
    plugin.generate_image(settings, device_config_dev)

    assert nasa.requests == 2
    assert downloads.call_count == 2
    assert _cache_files(device_config_dev) == []


def test_another_picture_size_is_a_separate_entry(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    nasa = _Nasa(monkeypatch)
    plugin, _downloads = _plugin(monkeypatch, device_config_dev)
    settings = {"customDate": "2024-03-18"}

    landscape = plugin.generate_image(settings, device_config_dev)
    device_config_dev.update_value("orientation", "vertical")
    portrait = plugin.generate_image(settings, device_config_dev)

    assert nasa.requests == 2
    assert portrait.size == landscape.size[::-1]


def test_an_unreadable_entry_is_fetched_again(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    nasa = _Nasa(monkeypatch)
    plugin, _downloads = _plugin(monkeypatch, device_config_dev)
    settings = {"customDate": "2024-03-18"}
    plugin.generate_image(settings, device_config_dev)
    [png] = Path(device_config_dev.plugin_image_dir).glob("apod_cache/*.png")
    png.write_bytes(b"not a png")

    image = plugin.generate_image(settings, device_config_dev)
    again = plugin.generate_image(settings, device_config_dev)

    assert nasa.requests == 2
    assert again.tobytes() == image.tobytes()


def test_the_cache_keeps_the_most_recently_used_entries(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    nasa = _Nasa(monkeypatch)
    plugin, _downloads = _plugin(monkeypatch, device_config_dev)
    cache_dir = Path(device_config_dev.plugin_image_dir) / "apod_cache"
    days = [f"2024-01-{n:02d}" for n in range(1, apod_mod._CACHE_MAX_ENTRIES + 1)]
    for index, day in enumerate(days):
        plugin.generate_image({"customDate": day}, device_config_dev)
        # The first day is the oldest entry, the last day the newest.
        for meta in cache_dir.glob(f"{day}_*.json"):
            os.utime(meta, (1_000_000 + index, 1_000_000 + index))
    assert nasa.requests == len(days)

    # Showing the oldest entry again makes it the most recently used...
    plugin.generate_image({"customDate": days[0]}, device_config_dev)
    # ...so a new date evicts the next oldest instead.
    plugin.generate_image({"customDate": "2024-02-01"}, device_config_dev)

    names = _cache_files(device_config_dev)
    assert len(names) == 2 * apod_mod._CACHE_MAX_ENTRIES
    assert not any(name.startswith(days[1]) for name in names)
    assert any(name.startswith(days[0]) for name in names)
    assert nasa.requests == len(days) + 1


def test_a_cache_that_cannot_be_written_still_renders(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any, tmp_path: Path
) -> None:
    _Nasa(monkeypatch)
    plugin, _downloads = _plugin(monkeypatch, device_config_dev)
    blocked = tmp_path / "plugins" / "apod_cache"
    blocked.write_text("a file where the folder should be")

    image = plugin.generate_image({"customDate": "2024-03-18"}, device_config_dev)

    assert image.size == plugin.get_oriented_dimensions(device_config_dev)

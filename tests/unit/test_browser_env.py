"""Local Chromium renders get an allowlisted environment, not the app's (E3).

The app loads API keys from ``.env`` into ``os.environ``. Local renders run
Chromium with web security off, so before this the browser inherited every key.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from utils import image_utils
from utils.browser_env import browser_environment

_SECRETS = {
    "NASA_SECRET": "nasa-key-value",
    "OPEN_AI_SECRET": "openai-key-value",
    "GOOGLE_AI_SECRET": "google-key-value",
    "INKYPI_PIN": "1234",
}


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _SECRETS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")


def _assert_no_secrets(env: dict[str, str]) -> None:
    leaked = set(env) & set(_SECRETS)
    assert not leaked, f"secrets passed to the browser: {sorted(leaked)}"
    assert not set(env.values()) & set(_SECRETS.values())


def test_environment_keeps_what_chromium_needs_and_drops_the_rest(
    secret_env: None,
) -> None:
    env = browser_environment()

    _assert_no_secrets(env)
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/root"
    assert env["LC_ALL"] == "C.UTF-8"


def test_overrides_are_applied(secret_env: None) -> None:
    env = browser_environment({"HOME": "/tmp/render", "TMPDIR": "/tmp/render"})
    assert env["HOME"] == "/tmp/render"
    assert env["TMPDIR"] == "/tmp/render"
    _assert_no_secrets(env)


def test_local_subprocess_render_does_not_inherit_api_keys(
    secret_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 1, b"", b"boom")

    monkeypatch.setattr(
        image_utils, "_find_browser_command", lambda *a, **k: ["chromium"]
    )
    monkeypatch.setattr(subprocess, "run", _run)

    image_utils._take_screenshot_once("file:///tmp/render.html", (8, 8), 1000, 1)

    assert "env" in seen, "the local render must pass an explicit environment"
    _assert_no_secrets(seen["env"])
    assert seen["env"]["PATH"] == "/usr/bin:/bin"


@pytest.fixture
def playwright_browser() -> Iterator[MagicMock]:
    with patch("playwright.sync_api.sync_playwright") as manager:
        chromium = manager.return_value.__enter__.return_value.chromium
        output = BytesIO()
        Image.new("RGB", (8, 8), "white").save(output, format="PNG")
        page = chromium.launch.return_value.new_page.return_value
        page.screenshot.return_value = output.getvalue()
        yield chromium


def test_playwright_render_does_not_inherit_api_keys(
    secret_env: None, playwright_browser: MagicMock
) -> None:
    pytest.importorskip("playwright.sync_api")

    image_utils._playwright_screenshot_html("/tmp/render.html", (8, 8))

    kwargs = playwright_browser.launch.call_args.kwargs
    assert "env" in kwargs, "Playwright must launch Chromium with an explicit env"
    _assert_no_secrets(kwargs["env"])

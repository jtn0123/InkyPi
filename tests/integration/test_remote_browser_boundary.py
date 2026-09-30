"""Exercise production Chromium flags/proxy with public fixtures and private canaries."""

from __future__ import annotations

import os
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.skipif(
    os.getenv("REQUIRE_BROWSER_SMOKE", "").lower() not in {"1", "true"},
    reason="Runs in the required browser lane with installed Chromium",
)


def test_remote_renderer_blocks_private_subresources_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils import image_utils, remote_rendering

    hits: list[str] = []

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            hits.append(self.path)
            private = f"http://127.0.0.1:{server.server_port}/private-canary"
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", private)
                self.end_headers()
                return
            body = (
                '<body style="margin:0;background:rgb(40,167,69)">Public fixture'
                f'<img src="{private}"><iframe src="{private}"></iframe>'
                f'<script>fetch("{private}");</script>'
                '<img src="http://public.test/redirect">'
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_connect = remote_rendering.connect_public

    def fixture_connect(url: str) -> socket.socket:
        # Only the controlled public fixture is mapped to this local server.
        # All private targets still traverse the real public-address validator.
        if url.startswith("http://public.test/"):
            return socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=2
            )
        return original_connect(url)

    monkeypatch.setattr(remote_rendering, "connect_public", fixture_connect)
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    cache = Path(executable).parents[2]
    revision = Path(executable).parents[1].name.removeprefix("chromium-")
    shell = list(cache.glob(f"chromium_headless_shell-{revision}/**/headless_shell"))
    shell += list(
        cache.glob(f"chromium_headless_shell-{revision}/**/chrome-headless-shell")
    )
    assert shell, "Install Playwright Chromium including Headless Shell for this lane"
    executable = str(shell[0])
    original_command = image_utils._find_browser_command
    monkeypatch.setattr(shutil, "which", lambda _: executable)

    def command(*args: Any, **kwargs: Any) -> list[str] | None:
        result = original_command(*args, **kwargs)
        assert result
        result[0] = executable
        return result

    monkeypatch.setattr(image_utils, "_find_browser_command", command)
    try:
        image, transient = image_utils._take_screenshot_once(
            "http://public.test/", (400, 300), 20_000, 1, 2000
        )
        assert image is not None
        assert not transient
        assert image.convert("RGB").getpixel((399, 299)) == (40, 167, 69)
        assert "/" in hits
        assert "/redirect" in hits
        assert not any("canary" in path for path in hits)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

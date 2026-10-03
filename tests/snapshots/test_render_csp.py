# pyright: reportMissingImports=false
"""End-to-end check that the plugin render CSP is enforced by real Chromium.

Plugin pages are rendered from ``file://`` with ``--disable-web-security``.
That flag relaxes same-origin checks but not CSP, so the meta policy in
``base_plugin/render/plugin.html`` must still stop a rendered page from
talking to the network while leaving inline scripts and remote images (RSS
thumbnails) working.
"""

from __future__ import annotations

import http.server
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_requires_browser = pytest.mark.skipif(
    os.getenv("REQUIRE_BROWSER_SMOKE", "").lower() not in ("1", "true"),
    reason=(
        "Renders HTML via Playwright Chromium. Set REQUIRE_BROWSER_SMOKE=1 to "
        "run it (see tests/snapshots/README.md)."
    ),
)

_PROBE_TEMPLATE = """{% extends "plugin.html" %}
{% block content %}
<img src="http://127.0.0.1:{{ port }}/img" alt="">
<script>
  fetch("http://127.0.0.1:{{ port }}/fetch").catch(() => {});
  navigator.sendBeacon("http://127.0.0.1:{{ port }}/beacon", "x");
  try { new WebSocket("ws://127.0.0.1:{{ port }}/ws"); } catch (e) {}
  document.documentElement.style.background = "rgb(0, 0, 255)";
  document.body.style.background = "rgb(0, 0, 255)";
</script>
{% endblock %}
"""


@pytest.fixture
def request_log() -> Iterator[tuple[int, list[str]]]:
    hits: list[str] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _record(self) -> None:
            hits.append(self.path)
            self.send_response(204)
            self.end_headers()

        do_GET = _record
        do_POST = _record

        def log_message(self, *_args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], hits
    finally:
        server.shutdown()
        server.server_close()


@_requires_browser
def test_render_csp_blocks_network_exfiltration(
    tmp_path: Path,
    request_log: tuple[int, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jinja2 import FileSystemLoader

    from plugins.base_plugin.base_plugin import BASE_PLUGIN_RENDER_DIR, BasePlugin

    monkeypatch.setenv("INKYPI_CHROMIUM_LOCK_DIR", str(tmp_path))
    port, hits = request_log
    (tmp_path / "probe.html").write_text(_PROBE_TEMPLATE, encoding="utf-8")

    plugin = BasePlugin({"id": "csp_probe"})
    plugin.env.loader = FileSystemLoader([str(tmp_path), BASE_PLUGIN_RENDER_DIR])

    image = plugin.render_image(
        (200, 120), "probe.html", None, {"port": port, "plugin_settings": {}}
    )

    # The inline script ran (CSP allows inline scripts for chart/calendar code)...
    assert image.convert("RGB").getpixel((100, 60)) == (0, 0, 255)
    # ...remote images still load, but every scripted network channel is blocked.
    assert "/img" in hits
    assert not {"/fetch", "/beacon", "/ws"} & set(hits), hits

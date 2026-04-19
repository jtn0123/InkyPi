# pyright: reportMissingImports=false
"""Shared helpers for Playwright-based browser tests."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest

CRITICAL_RESPONSE_TYPES = {"document", "script", "stylesheet", "xhr", "fetch"}


def leaflet_stub_js() -> str:
    """Return a minimal Leaflet stub to prevent browser-side map side effects."""
    return """
      (() => {
        function chain() { return this; }
        function markerFactory() {
          return {
            addTo: chain,
            bindPopup: chain,
            openPopup: chain,
            setLatLng: chain,
          };
        }
        window.L = {
          map() {
            return {
              setView: chain,
              on: chain,
              off: chain,
              fitBounds: chain,
              addLayer: chain,
              removeLayer: chain,
              invalidateSize: chain,
              closePopup: chain,
            };
          },
          tileLayer() {
            return { addTo: chain };
          },
          marker: markerFactory,
          latLng(lat, lng) {
            return { lat, lng };
          },
        };
      })();
    """


def stub_leaflet(page):
    """Intercept local Leaflet asset requests and return stubs."""
    page.route(
        "**/static/vendor/leaflet/leaflet.css",
        lambda route: route.fulfill(status=200, content_type="text/css", body=""),
    )
    page.route(
        "**/static/vendor/leaflet/leaflet.js",
        lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=leaflet_stub_js()
        ),
    )


class RuntimeCollector:
    """Attach console error / JS exception listeners to a Playwright page."""

    def __init__(self, page, base_url: str = ""):
        self.page = page
        self.base_url = base_url
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.request_failures: list[dict] = []
        self.response_failures: list[dict] = []

        def handle_console(msg):
            if msg.type != "error":
                return
            text = msg.text
            # Ignore Leaflet asset-loading noise from the stubbed map bootstrap.
            if "integrity" in text and "leaflet" in text.lower():
                return
            self.console_errors.append(text)

        page.on("pageerror", lambda exc: self.page_errors.append(str(exc)))
        page.on("console", handle_console)
        page.on(
            "requestfailed",
            lambda request: (
                self.request_failures.append(
                    {
                        "url": request.url,
                        "resource_type": request.resource_type,
                        "failure": request.failure or "",
                    }
                )
                if (not base_url or request.url.startswith(base_url))
                and request.resource_type in CRITICAL_RESPONSE_TYPES
                else None
            ),
        )
        page.on(
            "response",
            lambda response: (
                self.response_failures.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "resource_type": response.request.resource_type,
                    }
                )
                if (not base_url or response.url.startswith(base_url))
                and response.status >= 400
                and response.request.resource_type in CRITICAL_RESPONSE_TYPES
                else None
            ),
        )

    def assert_no_errors(
        self, screenshot_dir: Path | str | None = None, name: str = "page"
    ):
        failures = []
        if self.page_errors:
            failures.append(f"pageerror: {self.page_errors[:5]}")
        if self.console_errors:
            failures.append(f"console error: {self.console_errors[:5]}")
        if self.request_failures:
            failures.append(f"request failures: {self.request_failures[:5]}")
        if self.response_failures:
            failures.append(f"response failures: {self.response_failures[:5]}")

        if failures:
            if screenshot_dir:
                screenshot_dir = (
                    Path(screenshot_dir)
                    if not isinstance(screenshot_dir, Path)
                    else screenshot_dir
                )
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                slug = name.replace("/", "_").replace("?", "_").replace("&", "_")
                path = screenshot_dir / f"{slug}.png"
                self.page.screenshot(path=str(path), full_page=True)
                failures.append(f"screenshot: {path}")
            pytest.fail("\n".join(failures))


def wait_for_app_ready(page, timeout: int = 10000):
    """Wait for DOM content loaded and page shell element."""
    page.wait_for_selector("[data-page-shell]", timeout=timeout)
    page.wait_for_timeout(300)


def navigate_and_wait(
    page, base_url: str, path: str, timeout: int = 30000
) -> RuntimeCollector:
    """Navigate to a page with leaflet stub, attach collectors, and wait for ready."""
    stub_leaflet(page)
    collector = RuntimeCollector(page, base_url)
    page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=timeout)
    wait_for_app_ready(page)
    return collector


def prepare_playlist(device_config_dev):
    """Seed device config with a Default playlist containing one clock instance."""
    from model import RefreshInfo

    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=0,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()


def _session_cookie_for_authed_user(flask_app) -> tuple[str, str]:
    """Return the Flask signed-session cookie (name, value) for ``authed=True``.

    Uses the app's real test client so the cookie is signed with the app's
    ``SECRET_KEY`` and uses the configured session interface. This means the
    resulting cookie is accepted by the live server thread without any
    patching of cookie serialization.

    Returns a tuple ``(cookie_name, cookie_value)`` suitable for passing to
    :meth:`playwright.sync_api.BrowserContext.add_cookies`.
    """
    cookie_name = flask_app.config.get("SESSION_COOKIE_NAME", "session")
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["authed"] = True
    # Flask's test client keeps cookies on ``client.get`` responses; the
    # session_transaction commit above stamps the signed cookie into the
    # client's cookie jar. Pull it out directly. ``client`` exposes a
    # ``CookieJar``-like object at ``_cookies`` across Werkzeug versions;
    # iterate defensively to tolerate newer/older APIs.
    raw_cookie: str | None = None
    jar = getattr(client, "_cookies", None)
    if jar is not None:
        # Werkzeug >=3 exposes a dict-like mapping keyed by
        # ``(domain, path, name)`` tuples.
        try:
            for key, cookie in jar.items():
                name = key[-1] if isinstance(key, tuple) else key
                if name == cookie_name:
                    raw_cookie = getattr(cookie, "value", cookie)
                    break
        except AttributeError:
            # Older API: jar is iterable of cookie objects.
            for cookie in jar:
                if getattr(cookie, "name", None) == cookie_name:
                    raw_cookie = getattr(cookie, "value", None)
                    break
    if raw_cookie is None:
        # Fallback: make a request so the Set-Cookie header is emitted and
        # parse it from there. Any exempt route works.
        resp = client.get("/login")
        set_cookie = resp.headers.get("Set-Cookie", "")
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith(f"{cookie_name}="):
                raw_cookie = part.split("=", 1)[1]
                break
    if raw_cookie is None:
        raise RuntimeError(
            "Could not materialize a signed session cookie from the Flask test "
            "client — authenticate_page cannot build a post_auth session."
        )
    return cookie_name, raw_cookie


def authenticate_page(page, flask_app, base_url: str) -> None:
    """Attach a signed ``authed=True`` session cookie to *page*'s context.

    Reusable by any integration test that needs a logged-in session before
    navigating. Today the app only gates routes when ``INKYPI_AUTH_PIN`` is
    set, so on the default test bootstrap this helper is a no-op from the
    server's perspective — it still exercises the cookie-injection plumbing
    so future auth-gated routes get coverage automatically via the
    ``post_auth`` parametrize variant.

    The cookie is scoped to the ``live_server`` host so it is sent on every
    request during the test. Call this BEFORE ``page.goto(...)``.
    """
    cookie_name, cookie_value = _session_cookie_for_authed_user(flask_app)
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    page.context.add_cookies(
        [
            {
                "name": cookie_name,
                "value": cookie_value,
                "domain": host,
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }
        ]
    )


def install_direct_manual_update(monkeypatch, flask_app):
    """Patch refresh_task.manual_update with a synchronous direct-render path.

    Background refresh workers are not running in browser tests, so the real
    ``manual_update`` short-circuits to a no-op. This helper installs a
    drop-in replacement that renders the plugin inline, writes the history
    sidecar via ``DisplayManager.display_image``, and updates
    ``device_config.refresh_info`` — exactly what the worker loop would do on
    a live system. Keeping this in one place avoids per-test duplication and
    keeps the production internal imports (model / plugin_registry /
    image_utils / time_utils) contained to the browser-helpers layer.
    """
    from model import RefreshInfo
    from plugins.plugin_registry import get_plugin_instance
    from utils.image_utils import compute_image_hash
    from utils.time_utils import now_device_tz

    display_manager = flask_app.config["DISPLAY_MANAGER"]
    refresh_task = flask_app.config["REFRESH_TASK"]
    device_config = flask_app.config["DEVICE_CONFIG"]

    monkeypatch.setattr(
        display_manager.display,
        "display_image",
        lambda *args, **kwargs: None,
        raising=True,
    )

    def _manual_update_direct(refresh_action):
        plugin_config = device_config.get_plugin(refresh_action.get_plugin_id())
        plugin = get_plugin_instance(plugin_config)
        current_dt = now_device_tz(device_config)
        image = refresh_action.execute(plugin, device_config, current_dt)
        refresh_info = refresh_action.get_refresh_info()
        display_manager.display_image(
            image,
            image_settings=plugin_config.get("image_settings", []),
            history_meta=refresh_info,
        )
        device_config.refresh_info = RefreshInfo(
            refresh_type=refresh_info.get("refresh_type"),
            plugin_id=refresh_info.get("plugin_id"),
            playlist=refresh_info.get("playlist"),
            plugin_instance=refresh_info.get("plugin_instance"),
            refresh_time=current_dt.isoformat(),
            image_hash=compute_image_hash(image),
        )
        device_config.write_config()
        return {"generate_ms": 0}

    monkeypatch.setattr(refresh_task, "manual_update", _manual_update_direct)

"""Smoke-test render endpoint (JTN-613).

Opt-in helper endpoint used by ``scripts/test_install_memcap.sh`` Phase 4 to
exercise the plugin render path in a live web-only container so that the peak
RSS sample actually reflects a real ``generate_image()`` call — not just the
idle web server.

The endpoint is registered **only** when ``INKYPI_SMOKE_FORCE_RENDER=1`` is set
in the environment at process startup, which the smoke-test Dockerfile does
explicitly. Production deployments never set this variable, so the route is
absent from production builds entirely (defense in depth on top of the CSRF
exemption below).

Why this exists
---------------
JTN-608 added idle/peak RSS budgets but the peak sample came back identical to
idle (58 MB both) because the render-exercise loop hit ``POST /update_now`` in a
``--web-only`` container without a CSRF token — the request was rejected with
403 before any plugin code ran. Rather than plumb CSRF token fetching through
the shell script, we expose a tiny CSRF-exempt render helper that is only
available when the smoke-test env var is set.

Unlike ``/update_now``, this endpoint deliberately does **not** push to the
display manager: the goal is to measure peak RSS of the render path (Pillow
buffer allocations, font loading, numpy temporaries) — not the display driver
path, which is already separately exercised by higher-level integration tests.
"""

from __future__ import annotations

import logging
import os

from flask import Flask, current_app, request

from utils.http_utils import json_error

logger = logging.getLogger(__name__)

#: Path of the opt-in smoke render endpoint. Prefixed with ``__`` so it is
#: visibly non-production and unlikely to collide with real routes.
SMOKE_RENDER_PATH = "/__smoke/render"

#: Environment variable that gates the entire endpoint. Evaluated at app
#: creation time (in ``register_smoke_endpoints``) so production builds never
#: even see the route.
SMOKE_RENDER_ENV_VAR = "INKYPI_SMOKE_FORCE_RENDER"

_TRUTHY = frozenset({"1", "true", "yes"})


def smoke_render_enabled() -> bool:
    """Return True if the smoke render endpoint should be registered/exempt.

    Read at request time rather than import time so tests can toggle the env
    var via monkeypatch without reloading the module.
    """
    return os.getenv(SMOKE_RENDER_ENV_VAR, "").strip().lower() in _TRUTHY


def register_smoke_endpoints(app: Flask) -> None:
    """Register the opt-in smoke render endpoint when the env var is set.

    If ``INKYPI_SMOKE_FORCE_RENDER`` is not truthy, this function is a no-op and
    no route is added, so production builds have zero attack surface from this
    module.
    """
    if not smoke_render_enabled():
        return

    logger.warning(
        "Registering %s — INKYPI_SMOKE_FORCE_RENDER is set. "
        "This endpoint must NEVER be enabled in production.",
        SMOKE_RENDER_PATH,
    )

    @app.route(SMOKE_RENDER_PATH, methods=["POST"])
    def smoke_render():  # noqa: D401 — Flask route, not a docstring target.
        """Render the named plugin in-process and return basic image metadata.

        Deliberately does NOT push the image to the display manager; the goal
        is to measure the allocation footprint of ``plugin.generate_image()``
        in isolation from the display driver. Response body is minimal so the
        caller (curl in the smoke script) does not have to parse anything.
        """
        # Defense in depth: re-check the env var at request time. If an
        # operator sets the variable at startup, hits this route once, and
        # then unsets it via ``docker exec``, the route will stop serving
        # even though Flask has already registered it.
        if not smoke_render_enabled():
            return json_error("Smoke render not enabled", status=404)

        plugin_id = (request.form.get("plugin_id") or "").strip()
        if not plugin_id:
            return json_error(
                "plugin_id is required",
                status=422,
                code="validation_error",
                details={"field": "plugin_id"},
            )

        device_config = current_app.config.get("DEVICE_CONFIG")
        if device_config is None:
            return json_error("device config unavailable", status=500)

        plugin_config = device_config.get_plugin(plugin_id)
        if not plugin_config:
            return json_error("Plugin not found", status=404)

        # Import lazily so non-smoke test runs never pull in the plugin
        # registry just to import this module.
        from plugins.plugin_registry import get_plugin_instance

        try:
            plugin = get_plugin_instance(plugin_config)
            image = plugin.generate_image({}, device_config)
        except Exception as exc:  # noqa: BLE001 — surface class for debugging only
            logger.exception("smoke render failed for plugin %s", plugin_id)
            return json_error(
                f"render failed: {type(exc).__name__}",
                status=500,
                code="smoke_render_error",
            )

        # Keep the response body tiny — the smoke script discards it.
        width = getattr(image, "width", None)
        height = getattr(image, "height", None)
        return (
            {
                "ok": True,
                "width": width,
                "height": height,
            },
            200,
        )

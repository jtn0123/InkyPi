"""Blackout / kill switch endpoint (B12).

``/api/blackout`` pauses every refresh and blanks the panel to white;
``/api/blackout?off=1`` (or ``DELETE /api/blackout``) lifts it and puts the
last frame back. GET is accepted as well as POST so either URL can live in a
browser bookmark or a phone home-screen shortcut — one tap, no form.

Auth
----
The route sits behind the app-wide PIN gate like every other administration
route (``app_setup/auth.py``): with a PIN configured, an unauthenticated
request is redirected to ``/login`` and lands back here afterwards.

POST and DELETE go through the normal CSRF check. GET is CSRF-exempt by
nature, and a GET that changes state is exactly what CSRF exploits — any page
could embed the URL and ride the session cookie (``SameSite=Lax`` still sends
it on a top-level navigation). So a mutating GET is only honoured when the
browser says it did not come from another site:

* ``Sec-Fetch-Site`` must be ``none`` (bookmark, typed URL, home-screen
  shortcut) or ``same-origin`` (a link inside InkyPi). Browsers set this header
  themselves and scripts cannot forge it.
* Without ``Sec-Fetch-Site`` (old browsers, curl), an ``Origin`` or
  ``Referer`` naming another host is refused.

That keeps the bookmark working while a link on someone else's page cannot
black out the frame.

Browser navigations get a redirect to the dashboard, which shows the blackout
banner and its Resume button; API clients get JSON.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from flask import Blueprint, current_app, redirect, request, url_for

from utils import blackout
from utils.http_utils import json_error, json_success

logger = logging.getLogger(__name__)

blackout_bp = Blueprint("blackout", __name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_TRUSTED_FETCH_SITES = frozenset({"none", "same-origin"})

#: Endpoints that push a frame to the panel on request. During blackout they
#: are refused up front with 409 rather than rendering and then being refused
#: by the refresh loop, so the caller sees why.
_PANEL_ENDPOINTS = frozenset(
    {
        "main.display_next",
        "main.refresh_alias",
        "playlist.display_next_in_playlist",
        "plugin.display_plugin_instance",
        "plugin.update_now",
        "history.history_redisplay",
    }
)


def _cross_site_reason() -> str | None:
    """Return why this GET looks cross-site, or ``None`` when it is safe."""
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site is not None:
        if fetch_site.strip().lower() in _TRUSTED_FETCH_SITES:
            return None
        # Fixed strings only: header values are client-controlled and must
        # not reach the log (log injection).
        return "Sec-Fetch-Site is not none/same-origin"
    for header in ("Origin", "Referer"):
        value = request.headers.get(header)
        if not value:
            continue
        if urlsplit(value).netloc.lower() != request.host.lower():
            return (
                "Origin from another host"
                if header == "Origin"
                else "Referer from another host"
            )
    return None


def _wants_html() -> bool:
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "text/html"


def _push(name: str, command: Any) -> str:
    """Queue a display command; return ``"queued"``, ``"done"`` or ``"failed"``."""
    refresh_task = current_app.config.get("REFRESH_TASK")
    if refresh_task is None:
        return "failed"
    try:
        refresh_task.run_display_command(name, command, wait=False)
    except Exception:  # noqa: BLE001 — the pause itself already took effect
        logger.warning("blackout: display command %s failed", name, exc_info=True)
        return "failed"
    return "queued" if getattr(refresh_task, "running", False) else "done"


def _apply(turn_on: bool) -> Any:
    device_config = current_app.config["DEVICE_CONFIG"]
    current = blackout.get_state(device_config)
    changed = current["active"] != turn_on
    display = "unchanged"

    if changed:
        state = blackout.set_active(device_config, turn_on)
        if turn_on:
            frame = blackout.blank_image(device_config)
            display = _push("blackout", lambda dm: dm.show_system_image(frame))
        else:
            display = _push("blackout_resume", lambda dm: dm.restore_last_frame())
    else:
        state = current

    if request.method == "GET" and _wants_html():
        return redirect(url_for("main.main_page"), code=303)

    if turn_on:
        message = "Blackout on: refreshes paused" if changed else "Already blacked out"
    else:
        message = "Blackout lifted: refreshes resumed" if changed else "Not blacked out"
    return json_success(
        message=message,
        active=state["active"],
        since=state["since"],
        changed=changed,
        display=display,
    )


@blackout_bp.route("/api/blackout", methods=["GET", "POST", "DELETE"])
def api_blackout() -> Any:
    """Turn blackout on, or off with ``?off=1`` / ``DELETE``."""
    if request.method == "GET":
        reason = _cross_site_reason()
        if reason is not None:
            logger.warning("blackout: refused cross-site GET (%s)", reason)
            return json_error(
                "Refusing a cross-site request; open the bookmark directly "
                "or use POST with a CSRF token.",
                status=403,
            )
    turn_on = request.method != "DELETE" and (
        request.args.get("off", "").strip().lower() not in _TRUTHY
    )
    return _apply(turn_on)


@blackout_bp.before_app_request
def _refuse_panel_writes_during_blackout() -> Any:
    if request.method != "POST" or request.endpoint not in _PANEL_ENDPOINTS:
        return None
    device_config = current_app.config.get("DEVICE_CONFIG")
    if device_config is None or not blackout.is_active(device_config):
        return None
    return json_error(blackout.BLOCKED_MESSAGE, status=409, code="blackout_active")

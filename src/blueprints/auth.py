"""Auth blueprint: login / logout routes for optional PIN authentication (JTN-286)."""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote, unquote, urlsplit

from flask import (
    Blueprint,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app_setup.auth import _verify_pin

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60
_LOGIN_TEMPLATE = "login.html"

# Allow-list of characters permitted in each decoded path segment. Any
# segment containing other characters causes the redirect to fall back to '/'.
_SAFE_SEGMENT_RE = re.compile(r"\A[A-Za-z0-9\-._~!$&'()*+,;=:@]*\Z")


def _safe_next_url(raw: str | None) -> str:
    """Return a safe same-origin redirect path, or '/' when *raw* is unsafe.

    Open-redirect guard (CodeQL py/url-redirection, JTN-326): the returned
    path is *reconstructed* from validated structural pieces (decoded path
    segments passed through an allow-list regex and then re-quoted) rather
    than being the raw request string. CodeQL's taint tracker does not
    propagate through validate-then-reuse patterns, so building the result
    from `quote()` of literal-safe components is what clears the alert.

    Rejects schemes, network-location URLs, protocol-relative URLs ('//evil'),
    backslash tricks ('/\\evil'), anything not starting with a single '/',
    and any segment containing characters outside the conservative path
    allow-list (e.g., control chars, '<', '>', whitespace).
    """
    if not raw:
        return "/"
    # Reject any control characters (newlines, tabs, NUL, etc.) up front —
    # urlsplit silently strips some of them, which could otherwise let a
    # payload bypass the segment allow-list.
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        return "/"
    # Reject protocol-relative ('//evil.com') and backslash-authority tricks.
    if not raw.startswith("/") or raw.startswith(("//", "/\\")):
        return "/"
    # Parse with a dummy scheme+host so urlsplit routes the value through the
    # standard URL parser; we only consume the path+query components below.
    try:
        parts = urlsplit("http://localhost" + raw)
    except ValueError:
        return "/"
    # Any netloc from the parse means the raw value slipped past the prefix
    # checks (shouldn't happen given the checks above, but belt-and-braces).
    if parts.netloc != "localhost":
        return "/"
    # Validate each decoded path segment against the allow-list, then rebuild
    # the path from re-quoted literals. This severs the taint chain from
    # `raw` to the returned value, since the result is a concatenation of
    # quote()'d validated segments with literal '/' separators.
    safe_segments: list[str] = []
    for segment in parts.path.split("/"):
        decoded = unquote(segment)
        if not _SAFE_SEGMENT_RE.fullmatch(decoded):
            return "/"
        safe_segments.append(quote(decoded, safe=""))
    safe_path = "/".join(safe_segments) or "/"
    if not safe_path.startswith("/"):
        safe_path = "/" + safe_path
    # Preserve an optional query string, rebuilt from allow-listed characters.
    if parts.query:
        if not re.fullmatch(r"[A-Za-z0-9\-._~!$&'()*+,;=:@/?%]*", parts.query):
            return safe_path
        safe_path = safe_path + "?" + parts.query
    return safe_path


def _is_locked_out() -> bool:
    """Return True when the session is in the rate-limit lockout window."""
    lockout_until = session.get("login_lockout_until")
    if lockout_until is None:
        return False
    if time.time() < lockout_until:
        return True
    # Lockout expired — reset counters
    session.pop("login_lockout_until", None)
    session.pop("login_failed_count", None)
    return False


def _record_failed_attempt() -> None:
    """Increment the failure counter and apply lockout when threshold is reached."""
    count = session.get("login_failed_count", 0) + 1
    session["login_failed_count"] = count
    if count >= _MAX_FAILED_ATTEMPTS:
        session["login_lockout_until"] = time.time() + _LOCKOUT_SECONDS
        logger.warning("PIN auth: lockout triggered after %d failed attempts", count)


@auth_bp.route("/login", methods=["GET"])  # type: ignore
def login_get() -> str | Response:
    next_url = _safe_next_url(request.args.get("next"))
    if session.get("authed") is True:
        return redirect(next_url)
    return render_template(_LOGIN_TEMPLATE, error=None, next=next_url)


@auth_bp.route("/login", methods=["POST"])  # type: ignore
def login_post() -> str | Response:
    """Validate submitted PIN and establish an authenticated session."""
    # CSRF token is checked by the global before_request handler in security_middleware.
    pin_hash = current_app.config.get("AUTH_PIN_HASH")
    if pin_hash is None:
        # Auth not enabled — redirect home
        return redirect("/")

    next_url = _safe_next_url(request.form.get("next"))

    if _is_locked_out():
        return render_template(
            _LOGIN_TEMPLATE,
            error="Too many failed attempts. Please wait 60 seconds and try again.",
            next=next_url,
        )

    submitted = request.form.get("pin", "")
    if _verify_pin(submitted, pin_hash):
        session["authed"] = True
        session.pop("login_failed_count", None)
        session.pop("login_lockout_until", None)
        return redirect(next_url)

    _record_failed_attempt()
    return render_template(
        _LOGIN_TEMPLATE, error="Incorrect PIN. Please try again.", next=next_url
    )


@auth_bp.route("/logout", methods=["GET"])  # type: ignore
def logout() -> Response:
    session.clear()
    return redirect(url_for("auth.login_get"))

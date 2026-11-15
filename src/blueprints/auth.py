"""Auth blueprint: login / logout routes for optional PIN authentication (JTN-286)."""

from __future__ import annotations

import logging
import math
import re
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

# ``flask.redirect`` returns a ``werkzeug.wrappers.Response``, not the
# ``flask.wrappers.Response`` subclass. Flask accepts either from a view, but
# the annotations here named only the subclass, so every redirect return was
# typed as something it is not.
from werkzeug.wrappers import Response as WerkzeugResponse

from app_setup.auth import (
    LOGIN_BACKOFF_KEY,
    LoginBackoff,
    _verify_pin,
    is_session_authenticated,
    mark_session_authenticated,
)

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

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


def _login_backoff() -> LoginBackoff:
    backoff = current_app.extensions.get(LOGIN_BACKOFF_KEY)
    if not isinstance(backoff, LoginBackoff):
        backoff = LoginBackoff()
        current_app.extensions[LOGIN_BACKOFF_KEY] = backoff
    return backoff


def _refused_response(message: str, retry_after_s: float, next_url: str) -> Response:
    body = render_template(_LOGIN_TEMPLATE, error=message, next=next_url)
    response = Response(body, status=429, mimetype="text/html")
    response.headers["Retry-After"] = str(math.ceil(retry_after_s))
    return response


def _paused_response(wait_s: float, next_url: str) -> Response:
    minutes = max(1, math.ceil(wait_s / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return _refused_response(
        "Too many failed attempts. Logins are paused; "
        f"try again in {minutes} {unit}.",
        wait_s,
        next_url,
    )


@auth_bp.route("/login", methods=["GET"])
def login_get() -> str | Response | WerkzeugResponse:
    next_url = _safe_next_url(request.args.get("next"))
    if is_session_authenticated(session, current_app):
        return redirect(next_url)
    return render_template(_LOGIN_TEMPLATE, error=None, next=next_url)


@auth_bp.route("/login", methods=["POST"])
def login_post() -> str | Response | WerkzeugResponse:
    """Validate submitted PIN and establish an authenticated session."""
    # CSRF token is checked by the global before_request handler in security_middleware.
    pin_hash = current_app.config.get("AUTH_PIN_HASH")
    if pin_hash is None:
        # Auth not enabled — redirect home
        return redirect("/")

    next_url = _safe_next_url(request.form.get("next"))

    # One backoff for the whole device, not per browser or address: clearing
    # cookies or switching address must not buy more guesses. While it runs,
    # even the right PIN waits; otherwise the pause wouldn't slow guessing.
    backoff = _login_backoff()
    with backoff.turn() as admitted:
        if not admitted:
            return _refused_response(
                "Another login is being checked. Try again in a moment.",
                backoff.turn_timeout_s,
                next_url,
            )
        wait_s = backoff.seconds_left()
        if wait_s > 0:
            return _paused_response(wait_s, next_url)

        submitted = request.form.get("pin", "")
        if _verify_pin(submitted, pin_hash):
            backoff.record_success()
            mark_session_authenticated(session, current_app)
            return redirect(next_url)

        pause_s = backoff.record_failure()
    if pause_s > 0:
        logger.warning(
            "PIN auth: %d failed attempts in a row; logins paused for %d s",
            backoff.failures,
            pause_s,
        )
        return _paused_response(pause_s, next_url)
    return render_template(
        _LOGIN_TEMPLATE, error="Incorrect PIN. Please try again.", next=next_url
    )


@auth_bp.route("/logout", methods=["GET"])
def logout() -> Response | WerkzeugResponse:
    session.clear()
    return redirect(url_for("auth.login_get"))

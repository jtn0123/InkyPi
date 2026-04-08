"""Auth blueprint: login / logout routes for optional PIN authentication (JTN-286)."""

from __future__ import annotations

import logging
import time

from flask import (
    Blueprint,
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


@auth_bp.route("/login", methods=["GET"])
def login_get():
    if session.get("authed") is True:
        return redirect(request.args.get("next") or "/")
    return render_template("login.html", error=None, next=request.args.get("next", "/"))


@auth_bp.route("/login", methods=["POST"])
def login_post():
    """Validate submitted PIN and establish an authenticated session."""
    # CSRF token is checked by the global before_request handler in security_middleware.
    pin_hash = current_app.config.get("AUTH_PIN_HASH")
    if pin_hash is None:
        # Auth not enabled — redirect home
        return redirect("/")

    next_url = request.form.get("next") or "/"

    if _is_locked_out():
        return render_template(
            "login.html",
            error="Too many failed attempts. Please wait 60 seconds and try again.",
            next=next_url,
        )

    submitted = request.form.get("pin", "")
    if _verify_pin(submitted, pin_hash):
        session["authed"] = True
        session.pop("login_failed_count", None)
        session.pop("login_lockout_until", None)
        return redirect(next_url if next_url.startswith("/") else "/")

    _record_failed_attempt()
    return render_template(
        "login.html", error="Incorrect PIN. Please try again.", next=next_url
    )


@auth_bp.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect(url_for("auth.login_get"))

"""Security middleware extracted from inkypi.py (JTN-289).

Single auditable home for:
  * Secret key bootstrap
  * HTTPS redirect
  * CSRF protection (token generation, request validation)
  * Rate limiting on mutating requests
  * Security response headers (HSTS, CSP, frame options, etc.)
"""

from __future__ import annotations

import logging
import os
import secrets
from time import perf_counter

from flask import Flask, g, redirect, request, session

from config import Config
from utils.http_utils import json_error
from utils.rate_limiter import SlidingWindowLimiter

logger = logging.getLogger(__name__)


# Constants (formerly magic numbers in inkypi.py)
_CACHE_1_YEAR = 31_536_000
_CACHE_1_DAY = 86_400
_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})
_RATE_EXEMPT = frozenset({"/healthz", "/readyz"})
_MUTATE_WINDOW = 60  # seconds
_MUTATE_MAX = 60  # requests per IP per window

_TRUTHY = frozenset({"1", "true", "yes"})


def _env_bool(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Secret key
# ---------------------------------------------------------------------------


def setup_secret_key(app: Flask, device_config: Config) -> None:
    """Resolve and persist the Flask SECRET_KEY for session signing."""
    secret = os.getenv("SECRET_KEY")
    if not secret:
        try:
            secret = device_config.load_env_key("SECRET_KEY")
        except Exception:
            secret = None
    if not secret:
        generated = secrets.token_hex(32)
        try:
            device_config.set_env_key("SECRET_KEY", generated)
            secret = generated
            logger.info("SECRET_KEY not set; generated and persisted to .env")
        except Exception as e:
            secret = generated
            logger.warning(
                "SECRET_KEY could not persist: %s — sessions won't survive restarts", e
            )
    app.secret_key = secret
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# ---------------------------------------------------------------------------
# HTTPS redirect
# ---------------------------------------------------------------------------


def setup_https_redirect(app: Flask, *, dev_mode: bool) -> None:
    """When INKYPI_FORCE_HTTPS=1 (and not in dev mode), redirect HTTP→HTTPS."""
    force_https = not dev_mode and _env_bool("INKYPI_FORCE_HTTPS")

    @app.before_request
    def _redirect_to_https():
        if not force_https:
            return None
        if (
            request.is_secure
            or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        ):
            return None
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------


def _generate_csrf_token() -> str:
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def _extract_csrf_token_from_request() -> str | None:
    """Extract the CSRF token from the request header, form data, or JSON body."""
    header_token = request.headers.get("X-CSRFToken")
    if header_token:
        return header_token
    content_type = request.content_type or ""
    if "form" in content_type:
        form_token = request.form.get("csrf_token")
        if form_token:
            return form_token
    if "json" in content_type:
        json_body = request.get_json(silent=True)
        if isinstance(json_body, dict):
            return json_body.get("_csrf_token")
    return None


def setup_csrf_protection(app: Flask) -> None:
    """Register CSRF token generation and per-request validation."""

    @app.context_processor
    def _inject_csrf_token():
        return {"csrf_token": _generate_csrf_token}

    @app.before_request
    def _check_csrf_token():
        if request.method in _CSRF_SAFE_METHODS:
            return None
        if request.path in _CSRF_EXEMPT_PATHS:
            return None
        token = session.get("_csrf_token")
        if not token:
            _generate_csrf_token()
            return json_error("CSRF token missing or invalid", status=403)
        request_token = _extract_csrf_token_from_request()
        if not request_token or not secrets.compare_digest(request_token, token):
            return json_error("CSRF token missing or invalid", status=403)
        return None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


_mutation_limiter = SlidingWindowLimiter(_MUTATE_MAX, _MUTATE_WINDOW)


def setup_rate_limiting(app: Flask) -> None:
    """Sliding-window per-IP rate limit on mutating requests."""

    @app.before_request
    def _rate_limit_mutations():
        if request.method in _CSRF_SAFE_METHODS:
            return None
        if request.path in _RATE_EXEMPT:
            return None
        addr = request.remote_addr or "unknown"
        allowed, _ = _mutation_limiter.check(addr)
        if not allowed:
            return json_error("Rate limit exceeded — try again shortly", status=429)
        return None


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


def setup_security_headers(app: Flask, *, dev_mode: bool) -> None:
    """Attach an after_request hook that sets security + caching headers."""

    @app.after_request
    def _set_security_headers(response):
        try:
            if _env_bool("INKYPI_REQUEST_TIMING"):
                t0 = getattr(g, "_t0", None)
                if t0 is not None:
                    elapsed_ms = int((perf_counter() - t0) * 1000)
                    # Emit on the "inkypi" logger so existing monkey-patches in
                    # tests/unit/test_inkypi.py catch it without modification.
                    import sys

                    inkypi_mod = sys.modules.get("inkypi")
                    timing_logger = (
                        getattr(inkypi_mod, "logger", None)
                        if inkypi_mod is not None
                        else None
                    ) or logging.getLogger("inkypi")
                    timing_logger.info(
                        "HTTP %s %s -> %s in %sms",
                        request.method,
                        request.path,
                        response.status_code,
                        elapsed_ms,
                    )
        except Exception:
            pass

        if request.path.startswith("/static/"):
            if any(
                request.path.endswith(ext)
                for ext in [
                    ".css",
                    ".js",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".gif",
                    ".svg",
                    ".woff",
                    ".woff2",
                    ".ttf",
                ]
            ):
                response.headers.setdefault(
                    "Cache-Control",
                    f"public, max-age={_CACHE_1_YEAR}, immutable",
                )
            else:
                response.headers.setdefault(
                    "Cache-Control", f"public, max-age={_CACHE_1_DAY}"
                )

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        try:
            if (
                request.is_secure
                or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
            ):
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains",
                )
        except Exception:
            pass
        try:
            csp_value = (
                os.getenv("INKYPI_CSP")
                or "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://unpkg.com; script-src 'self'; font-src 'self' data: https:"
            )
            report_only = dev_mode or _env_bool("INKYPI_CSP_REPORT_ONLY")
            header_name = (
                "Content-Security-Policy-Report-Only"
                if report_only
                else "Content-Security-Policy"
            )
            if header_name not in response.headers:
                response.headers[header_name] = csp_value
        except Exception:
            pass
        try:
            # Resolve the symbol from the inkypi module so monkey-patches in
            # tests/unit/test_inkypi.py affect the call here too.
            import sys

            inkypi_mod = sys.modules.get("inkypi")
            pop_fn = (
                getattr(inkypi_mod, "pop_hot_reload_info", None)
                if inkypi_mod is not None
                else None
            )
            if pop_fn is None:
                from plugins.plugin_registry import pop_hot_reload_info as pop_fn
            info = pop_fn()
            if info and dev_mode:
                response.headers.setdefault(
                    "X-InkyPi-Hot-Reload",
                    f"{info['plugin_id']}:{int(info['reloaded'])}",
                )
        except Exception:
            pass
        return response

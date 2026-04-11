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

from flask import Flask, abort, g, make_response, redirect, request, session

from config import Config
from utils.http_utils import json_error
from utils.rate_limit import make_auth_bucket, make_mutating_bucket, make_refresh_bucket
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

#: Default allow-list of hostnames that may appear in a redirect ``Location``
#: header when upgrading HTTP to HTTPS. Operators can override this via the
#: ``INKYPI_ALLOWED_HOSTS`` env var (comma-separated). Only requests whose
#: ``Host`` header matches one of these entries are eligible for the HTTPS
#: upgrade redirect — everything else is rejected with a 400 to prevent
#: open-redirect attacks via spoofed ``Host`` headers (JTN-317, CodeQL
#: ``py/url-redirection`` alert #52).
_DEFAULT_ALLOWED_HOSTS = "inkypi.local,localhost,127.0.0.1"


def _env_bool(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


def _load_allowed_hosts() -> frozenset[str]:
    """Parse ``INKYPI_ALLOWED_HOSTS`` into a lowercase frozenset.

    Read at request time (not import time) so tests and operators can
    override the allow-list via environment variables without having to
    reload the module. Hostnames are compared case-insensitively and
    without any port suffix.
    """
    raw = os.getenv("INKYPI_ALLOWED_HOSTS") or _DEFAULT_ALLOWED_HOSTS
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


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
        # Defend against open-redirect via spoofed Host header (JTN-317,
        # CodeQL py/url-redirection alert #52). ``request.url`` is
        # built from the client-supplied ``Host`` header, so using it
        # directly in a ``Location`` header lets an attacker point the
        # redirect at an arbitrary domain. Instead we:
        #   1. Validate the request host against an allow-list.
        #   2. Rebuild the redirect target from the allow-listed host
        #      value (not the raw header) plus the request path.
        allowed_hosts = _load_allowed_hosts()
        raw_host = request.host or ""
        host_name, _sep, host_port = raw_host.partition(":")
        host_name = host_name.lower()
        if host_name not in allowed_hosts:
            abort(400, description="Invalid host")
        # Rebuild the authority from the allow-listed host. Preserving
        # the port lets ``localhost:5000`` → ``https://localhost:5000``
        # still work for local development.
        safe_authority = host_name
        # ``request.host`` already ran through Werkzeug parsing, so
        # the port (if present) is digits-only; still, guard it.
        if host_port and host_port.isdigit():
            safe_authority = f"{host_name}:{host_port}"
        # Preserve path + query string. ``full_path`` always ends with
        # a ``?`` even when there are no query args, so strip it.
        path_and_query = request.full_path
        if path_and_query.endswith("?"):
            path_and_query = path_and_query[:-1]
        # NOSONAR — the https:// literal is intentional: we are
        # upgrading the request to https. SonarCloud rule S5332 is a
        # false positive here.
        url = f"https://{safe_authority}{path_and_query}"  # NOSONAR
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

#: Paths that receive stricter per-IP token-bucket limiting (POST only).
#: /display-next is the canonical refresh endpoint; /refresh is a backward-
#: compatible alias; /login is the PIN-auth endpoint.
_AUTH_RATE_PATHS = frozenset({"/login"})
_REFRESH_RATE_PATHS = frozenset({"/display-next", "/refresh"})

#: High-cost mutating endpoints that can saturate CPU or hardware resources.
#: These receive an intermediate token-bucket limit (10/min per IP) — stricter
#: than the global sliding-window (60/min) but looser than /login (3/min).
#: /api/refresh/* is matched by prefix rather than exact path (see middleware).
_MUTATING_RATE_PATHS = frozenset({"/save_plugin_settings", "/update_now"})
_MUTATING_RATE_PREFIX = "/api/refresh/"

_mutation_limiter = SlidingWindowLimiter(_MUTATE_MAX, _MUTATE_WINDOW)

# Endpoint-specific token-bucket limiters (lazy-initialised at first call to
# setup_rate_limiting so env vars set after import are respected).
_auth_bucket = None
_refresh_bucket = None
_mutating_bucket = None


def _is_mutating_path(path: str) -> bool:
    """Return True if *path* matches a high-cost mutating endpoint."""
    return path in _MUTATING_RATE_PATHS or path.startswith(_MUTATING_RATE_PREFIX)


def _apply_token_bucket_limits(path: str, addr: str):
    """Check per-endpoint token-bucket limits; return a 429 response or None.

    Extracted to keep ``_rate_limit_mutations`` below SonarCloud's cognitive
    complexity threshold (S3776).
    """
    if path in _AUTH_RATE_PATHS and not _auth_bucket.try_acquire(addr):  # type: ignore[union-attr]
        body, code = json_error("Too many login attempts — try again later", status=429)
        resp = make_response(body, code)
        resp.headers["Retry-After"] = "30"
        return resp
    if path in _REFRESH_RATE_PATHS and not _refresh_bucket.try_acquire(addr):  # type: ignore[union-attr]
        body, code = json_error(
            "Refresh rate limit exceeded — try again later", status=429
        )
        resp = make_response(body, code)
        resp.headers["Retry-After"] = "6"
        return resp
    if _is_mutating_path(path) and not _mutating_bucket.try_acquire(addr):  # type: ignore[union-attr]
        body, code = json_error("Too many requests — try again later", status=429)
        resp = make_response(body, code)
        resp.headers["Retry-After"] = "6"
        return resp
    return None


def setup_rate_limiting(app: Flask) -> None:
    """Sliding-window per-IP rate limit on mutating requests.

    Also applies stricter token-bucket limits to the /login and
    /display-next (refresh) endpoints to prevent brute-force and
    refresh-storming attacks (JTN-447).

    Additionally applies an intermediate token-bucket limit to high-cost
    mutating endpoints (/save_plugin_settings, /update_now, /api/refresh/*)
    to prevent CPU saturation and hardware abuse (JTN-513).
    """
    global _auth_bucket, _refresh_bucket, _mutating_bucket
    _auth_bucket = make_auth_bucket()
    _refresh_bucket = make_refresh_bucket()
    _mutating_bucket = make_mutating_bucket()

    @app.before_request
    def _rate_limit_mutations():
        if request.method in _CSRF_SAFE_METHODS:
            return None
        if request.path in _RATE_EXEMPT:
            return None
        addr = request.remote_addr or "unknown"
        bucket_resp = _apply_token_bucket_limits(request.path, addr)
        if bucket_resp is not None:
            return bucket_resp
        # --- General sliding-window limit (all other mutations) ---
        allowed, _ = _mutation_limiter.check(addr)
        if not allowed:
            return json_error("Rate limit exceeded — try again shortly", status=429)
        return None


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


_STATIC_ASSET_EXTS = (
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
)
_DEFAULT_CSP = (
    "default-src 'self'; img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com; "
    "script-src 'self'; font-src 'self' data: https:"
)


def _emit_request_timing_log(response) -> None:
    """Emit a timing log line if INKYPI_REQUEST_TIMING is set."""
    if not _env_bool("INKYPI_REQUEST_TIMING"):
        return
    t0 = getattr(g, "_t0", None)
    if t0 is None:
        return
    elapsed_ms = int((perf_counter() - t0) * 1000)
    # Emit on the "inkypi" logger so existing monkey-patches in
    # tests/unit/test_inkypi.py catch it without modification.
    import sys

    inkypi_mod = sys.modules.get("inkypi")
    timing_logger = (
        getattr(inkypi_mod, "logger", None) if inkypi_mod is not None else None
    ) or logging.getLogger("inkypi")
    timing_logger.info(
        "HTTP %s %s -> %s in %sms",
        request.method,
        request.path,
        response.status_code,
        elapsed_ms,
    )


def _apply_static_cache_headers(response) -> None:
    """Set long-lived Cache-Control on hashed static assets."""
    if not request.path.startswith("/static/"):
        return
    if any(request.path.endswith(ext) for ext in _STATIC_ASSET_EXTS):
        response.headers.setdefault(
            "Cache-Control",
            f"public, max-age={_CACHE_1_YEAR}, immutable",
        )
    else:
        response.headers.setdefault("Cache-Control", f"public, max-age={_CACHE_1_DAY}")


def _apply_baseline_security_headers(response) -> None:
    """Set the always-on baseline security headers."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )


def _apply_hsts_header(response) -> None:
    """Set HSTS when the request arrived over HTTPS (or via a TLS proxy)."""
    is_https = (
        request.is_secure
        or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    )
    if is_https:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )


def _apply_csp_header(response, *, dev_mode: bool) -> None:
    """Set the Content-Security-Policy header (report-only in dev mode)."""
    csp_value = os.getenv("INKYPI_CSP") or _DEFAULT_CSP
    if "report-uri" not in csp_value:
        csp_value = csp_value.rstrip("; ") + "; report-uri /api/csp-report"
    report_only = dev_mode or _env_bool("INKYPI_CSP_REPORT_ONLY")
    header_name = (
        "Content-Security-Policy-Report-Only"
        if report_only
        else "Content-Security-Policy"
    )
    if header_name not in response.headers:
        response.headers[header_name] = csp_value


def _apply_hot_reload_header(response, *, dev_mode: bool) -> None:
    """Surface the dev-mode plugin hot-reload status as a response header."""
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


def setup_security_headers(app: Flask, *, dev_mode: bool) -> None:
    """Attach an after_request hook that sets security + caching headers.

    The hook delegates to small helper functions per concern so the
    cognitive complexity stays low (SonarCloud S3776).
    """

    @app.after_request
    def _set_security_headers(response):
        for step in (
            _emit_request_timing_log,
            _apply_static_cache_headers,
            _apply_baseline_security_headers,
            _apply_hsts_header,
        ):
            try:
                step(response)
            except Exception:
                pass
        try:
            _apply_csp_header(response, dev_mode=dev_mode)
        except Exception:
            pass
        try:
            _apply_hot_reload_header(response, dev_mode=dev_mode)
        except Exception:
            pass
        return response

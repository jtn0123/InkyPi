"""Optional PIN authentication middleware (JTN-286).

When INKYPI_AUTH_PIN env var is set, or device_config has auth.pin, all routes
except the skip-list require a valid authenticated session.

When neither is configured the module registers no handlers and the app
behaves identically to today.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from typing import TYPE_CHECKING

from flask import Flask, redirect, request, session, url_for

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

# Paths that never require authentication
_AUTH_SKIP_PREFIXES = ("/static/",)
_AUTH_SKIP_EXACT = frozenset({"/login", "/logout", "/sw.js", "/api/health"})
# Also skip Flask/Werkzeug internal health probes registered by health.py
_AUTH_SKIP_HEALTH = frozenset({"/healthz", "/readyz"})

_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60

# Per-process random salt — never persisted, never logged
_SCRYPT_SALT = secrets.token_bytes(32)
_SCRYPT_N = 2**14  # 16 384 — fast enough on Pi Zero, still strong
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def _hash_pin(pin: str) -> bytes:
    """Return a scrypt-derived key for *pin* using the per-process salt."""
    return hashlib.scrypt(
        pin.encode(),
        salt=_SCRYPT_SALT,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )


def _verify_pin(candidate: str, stored_hash: bytes) -> bool:
    """Constant-time comparison of candidate PIN against stored hash."""
    candidate_hash = _hash_pin(candidate)
    return hmac.compare_digest(candidate_hash, stored_hash)


def _should_skip_auth() -> bool:
    """Return True when the current request path is exempt from authentication."""
    path = request.path
    if path in _AUTH_SKIP_EXACT:
        return True
    if path in _AUTH_SKIP_HEALTH:
        return True
    return any(path.startswith(prefix) for prefix in _AUTH_SKIP_PREFIXES)


def init_auth(app: Flask, device_config: Config) -> None:
    """Wire up PIN auth if a PIN is configured; otherwise log and return."""
    pin = os.environ.get("INKYPI_AUTH_PIN")
    if not pin:
        try:
            auth_cfg = device_config.get_config("auth", {})
            if isinstance(auth_cfg, dict):
                pin = auth_cfg.get("pin")
        except Exception:
            pin = None

    # Reject anything that isn't a non-empty string (e.g. MagicMock in tests)
    if not pin or not isinstance(pin, str):
        logger.info(
            "PIN auth disabled (INKYPI_AUTH_PIN not set, no auth.pin in config)"
        )
        return

    # Hash immediately — the plaintext PIN is never stored beyond this scope
    pin_hash = _hash_pin(pin)
    app.config["AUTH_ENABLED"] = True
    app.config["AUTH_PIN_HASH"] = pin_hash
    logger.info("PIN auth enabled")

    @app.before_request
    def _require_auth():
        if _should_skip_auth():
            return None
        if session.get("authed") is True:
            return None
        next_url = request.url
        return redirect(url_for("auth.login_get", next=next_url))

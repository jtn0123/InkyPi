"""Best-effort webhook notification helper for InkyPi.

Sends a JSON POST to each configured webhook URL when a plugin refresh fails
or its circuit breaker opens.  All exceptions are swallowed — this helper
must never block or raise so that it cannot interfere with the refresh cycle.
"""

import logging
from typing import Any
from urllib.parse import urlsplit

# ``requests`` is imported lazily via ``__getattr__`` to keep it off the
# startup path (JTN-606).  Webhooks are only fired when a plugin refresh
# fails, so importing the library at module load time is wasteful.
# Existing tests that patch ``utils.webhooks.requests.post`` still work
# because module ``__getattr__`` exposes the name on first attribute access.

logger = logging.getLogger(__name__)


def __getattr__(name: str) -> Any:
    """Lazy module-level attribute resolver for ``requests`` (JTN-606)."""
    if name == "requests":
        import requests as _requests

        # Cache on the module so subsequent accesses skip this dispatcher.
        globals()["requests"] = _requests
        return _requests
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def send_failure_webhook(
    urls: list[str],
    payload: dict[str, Any],
    timeout: float = 1.0,
) -> None:
    """POST *payload* as JSON to every URL in *urls* (best-effort, no retries).

    Args:
        urls: List of webhook endpoint URLs to notify.
        payload: JSON-serialisable dictionary sent as the request body.
        timeout: Per-request timeout in seconds (default 1.0).  Requests that
            exceed this limit are abandoned silently.

    Guarantees:
        - Never raises any exception.
        - Logs a WARNING on failure, INFO on success.
        - Uses an explicit timeout so a slow webhook cannot block the caller.
    """
    if not urls:
        return

    # Trigger the lazy ``__getattr__`` so ``requests`` is bound on the module.
    import utils.webhooks as _self

    requests_mod = _self.requests

    for url in urls:
        target = _redact_webhook_url(url)
        try:
            response = requests_mod.post(url, json=payload, timeout=timeout)
            logger.info(
                "webhook: sent | target=%s status=%s",
                target,
                response.status_code,
            )
        except Exception as exc:
            # No traceback / str(exc): requests embeds the full URL (and so
            # the token) in its exception messages.
            logger.warning(
                "webhook: failed | target=%s error=%s",
                target,
                type(exc).__name__,
            )


def _redact_webhook_url(url: object) -> str:
    """Return only ``scheme://host[:port]`` of *url* for logging.

    Slack/Discord/ntfy webhook URLs carry their secret in the path or query,
    and logs are readable through ``/api/logs``, so nothing past the
    authority (nor any ``user:pass@`` userinfo) is ever logged.
    """
    try:
        parsed = urlsplit(str(url))
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return "<invalid-url>"
    if not parsed.scheme or not host:
        return "<invalid-url>"
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}" + (f":{port}" if port else "")

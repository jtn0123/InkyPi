"""Best-effort webhook notification helper for InkyPi.

Sends a JSON POST to each configured webhook URL when a plugin refresh fails
or its circuit breaker opens.  All exceptions are swallowed — this helper
must never block or raise so that it cannot interfere with the refresh cycle.
"""

import logging
from typing import Any

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
        try:
            response = requests_mod.post(url, json=payload, timeout=timeout)
            logger.info(
                "webhook: sent | url=%s status=%s",
                url,
                response.status_code,
            )
        except Exception:
            logger.warning(
                "webhook: failed | url=%s",
                url,
                exc_info=True,
            )

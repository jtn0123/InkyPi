"""Best-effort webhook notification helper for InkyPi.

Sends a JSON POST to each configured webhook URL when a plugin refresh fails
or its circuit breaker opens.  All exceptions are swallowed — this helper
must never block or raise so that it cannot interfere with the refresh cycle.
"""

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


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

    for url in urls:
        try:
            response = requests.post(url, json=payload, timeout=timeout)
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

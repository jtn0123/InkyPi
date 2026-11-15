"""Poll-based waiting for tests that observe work finishing on another thread.

``RefreshTask.manual_update`` returns as soon as the image is saved; the
display push, health record and benchmark save land a moment later on the
refresh thread. Assert on those with :func:`wait_until` instead of reading
them straight after the call or sleeping a fixed span.
"""

from __future__ import annotations

import time
from collections.abc import Callable


def wait_until(
    predicate: Callable[[], object], timeout: float = 5.0, interval: float = 0.01
) -> bool:
    """Poll *predicate* until it is truthy or *timeout* seconds pass.

    Returns whether it became truthy; the final check runs after the deadline
    so a predicate that turns true at the last moment is not missed.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())

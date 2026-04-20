"""Exception types for plugin execution.

Defines a hierarchy of errors so the refresh task can distinguish permanent
configuration failures (bad URL, unsupported scheme, malformed settings)
from transient failures (network hiccups, timeouts) that are worth retrying.

Permanent errors are re-raised by the retry loop after a single attempt —
they will never succeed on retry and retrying only wastes CPU cycles and
spams the logs on every scheduled playlist tick (see JTN-778).
"""

from __future__ import annotations


class PermanentPluginError(RuntimeError):
    """A plugin failure that is guaranteed not to succeed on retry.

    Raise this when the failure is structural rather than environmental:

    - Invalid URL (bad scheme, SSRF-blocked address, malformed URL)
    - Missing required configuration (API key, album name)
    - Malformed settings that would fail the same way on every attempt

    The refresh task retry loop recognises this exception and skips the
    remaining attempts, so a single scheduled playlist tick with a broken
    plugin instance costs one validation run instead of two.

    Subclasses :class:`RuntimeError` so existing ``except RuntimeError``
    handlers (e.g. the plugin blueprint's fallback in JTN-776) continue to
    catch it without any change.
    """

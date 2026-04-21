"""Exception types for plugin execution.

Defines a hierarchy of errors so the refresh task can distinguish permanent
configuration failures (bad URL, unsupported scheme, malformed settings)
from transient failures (network hiccups, timeouts) that are worth retrying.

Permanent errors are re-raised by the retry loop after a single attempt —
they will never succeed on retry and retrying only wastes CPU cycles and
spams the logs on every scheduled playlist tick (see JTN-778).
"""

from __future__ import annotations

# Canonical URL validator messages. Keeping these as module constants gives us
# an explicit whitelist that :meth:`URLValidationError.safe_message` can check
# against before any validator text reaches an HTTP response body — this is
# what lets the blueprint return a specific error reason without tripping
# CodeQL's ``py/stack-trace-exposure`` rule (JTN-776).
#
# The hierarchy lives here (rather than in ``utils.security_utils``) so that
# modules which need to name-check the exception type — most notably the
# subprocess worker and tests pinning the cross-process contract — can do so
# without importing ``security_utils``. That separation is enforced by a
# SonarCloud architecture rule; see JTN-776 PR #563.
URL_ERR_EMPTY = "URL must not be empty"
URL_ERR_SCHEME = "URL scheme must be http or https"
URL_ERR_NO_HOST = "URL must include a hostname"
URL_ERR_LOCALHOST = "URL must not target localhost"
URL_ERR_UNRESOLVABLE = "Cannot resolve hostname"
URL_ERR_PRIVATE = (
    "URL must not resolve to a private, loopback, link-local, "
    "reserved, or multicast address"
)
URL_VALIDATOR_MESSAGES: frozenset[str] = frozenset(
    {
        URL_ERR_EMPTY,
        URL_ERR_SCHEME,
        URL_ERR_NO_HOST,
        URL_ERR_LOCALHOST,
        URL_ERR_UNRESOLVABLE,
        URL_ERR_PRIVATE,
    }
)
_URL_ERR_GENERIC = "URL failed validation"


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


class URLValidationError(PermanentPluginError):
    """Raised by plugins when a user-supplied URL fails SSRF/scheme validation.

    Subclasses :class:`PermanentPluginError` (itself a :class:`RuntimeError`)
    so the refresh-task retry loop skips extra attempts (JTN-778) and
    existing ``except RuntimeError`` blocks in plugin code keep working.
    The plugin blueprint catches this subclass specifically to return HTTP
    4xx with the validator message instead of a generic 500 (JTN-776).

    Callers returning this error to an HTTP client MUST use
    :meth:`safe_message` rather than ``str(self)`` — the former looks the
    reason up in a whitelist of known hardcoded validator strings, breaking
    any accidental information-exposure taint flow.
    """

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        # ``reason`` is the raw validator string from :func:`validate_url`.
        # When the plugin wraps ``ValueError`` the message is "Invalid URL: X"
        # where X is from :data:`URL_VALIDATOR_MESSAGES`; callers can pass the
        # validator text directly via ``reason`` to avoid string parsing.
        self.reason = reason if reason is not None else _extract_reason(message)

    def safe_message(self) -> str:
        """Return a response-safe description of the validation failure.

        The returned string is always one of two things:

        * ``"Invalid URL: <validator text>"`` where ``<validator text>`` is a
          member of :data:`URL_VALIDATOR_MESSAGES` (an immutable set of
          hardcoded strings in this module), or
        * ``"Invalid URL: URL failed validation"`` as a fallback.

        Because the output is selected from a constant set rather than derived
        from the exception instance, this satisfies CodeQL's
        ``py/stack-trace-exposure`` rule.
        """
        if self.reason in URL_VALIDATOR_MESSAGES:
            return f"Invalid URL: {self.reason}"
        return f"Invalid URL: {_URL_ERR_GENERIC}"


class ScreenshotBackendError(RuntimeError):
    """Raised when the chromium screenshot backend fails transiently after retry.

    On Pi Zero 2 W (and other memory-constrained hardware) the chromium
    subprocess can intermittently time out or exit without producing output
    when the device is under memory pressure.  :func:`utils.image_utils.take_screenshot`
    absorbs the single-tick flake by retrying once with a fresh browser
    process after a short backoff.  When both attempts still fail to produce
    an image, this exception is raised so the plugin blueprint can surface
    a specific HTTP 503 ``backend_unavailable`` response instead of a
    generic 500 ``internal_error`` (JTN-789).

    Subclasses :class:`RuntimeError` so existing ``except RuntimeError``
    handlers in plugin code continue to catch it.  Kept in this module (not
    in ``utils.security_utils`` or a Flask-aware module) so it is importable
    from both the plugin subprocess worker — which may not have a Flask app
    context — and the ``blueprints.plugin`` translator.
    """


def _extract_reason(message: str) -> str:
    """Extract the validator text from a wrapped "Invalid URL: X" message."""
    prefix = "Invalid URL: "
    if message.startswith(prefix):
        return message[len(prefix) :]
    return message

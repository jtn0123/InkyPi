"""Expected failures the core reports, with no knowledge of HTTP.

The refresh loop and other core code raise these so they never import the
web layer. The web layer turns each one into a status code and a response
code in one place: :func:`utils.backend_errors.route_error_for`.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base for failures the user should be told about, not shown as a crash."""

    default_message = "The request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class RefreshTaskUnavailable(DomainError):
    """The background refresh loop is not running, so nothing can be displayed."""

    default_message = "Display refresh service is not running"


class RefreshLoopBusy(DomainError):
    """The loop stayed busy with other work, so the request was withdrawn unrun."""

    default_message = (
        "The device is still busy with another refresh. Try again shortly."
    )


class PluginNotFound(DomainError):
    """The request names a plugin that is not installed."""

    default_message = "Plugin not found"


class PluginRenderFailed(DomainError, RuntimeError):
    """The plugin could not produce its image.

    Plugins raise :class:`RuntimeError` for a failure they know about (a
    missing key, a service that is down). :func:`as_render_failure` turns
    one into this error, on the refresh loop and in a direct render alike,
    so every display route reports a broken plugin the same way. The
    plugin's error is the ``__cause__`` and this error's text repeats it for
    the log. Routes answer with :attr:`default_message`, or, when the cause
    has an answer of its own (a rejected URL, a provider refusal, the
    screenshot backend down), with that.

    Also a :class:`RuntimeError`, so code that caught the plugin's
    ``RuntimeError`` still catches it.
    """

    default_message = "Plugin image generation failed"


def as_render_failure(error: Exception) -> Exception:
    """Return *error* as the failure the display routes report.

    A plugin's :class:`RuntimeError` becomes :class:`PluginRenderFailed`
    with *error* as its cause. Anything else is returned unchanged: a
    timeout has its own answer, and any other type is an internal error.
    """
    if isinstance(error, PluginRenderFailed) or not isinstance(error, RuntimeError):
        return error
    failed = PluginRenderFailed(str(error) or None)
    failed.__cause__ = error
    return failed

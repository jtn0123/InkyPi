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

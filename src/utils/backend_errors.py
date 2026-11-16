"""Typed backend route errors and a shared boundary for JSON handlers."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from utils.api_responses import APIError
from utils.blackout import BLOCKED_MESSAGE, BlackoutActiveError
from utils.domain_errors import (
    DomainError,
    PluginNotFound,
    PluginRenderFailed,
    RefreshLoopBusy,
    RefreshTaskUnavailable,
)
from utils.plugin_errors import (
    MANUAL_UPDATE_TIMEOUT_MSG,
    SCREENSHOT_BACKEND_UNAVAILABLE_MSG,
    ProviderReportedPluginError,
    ScreenshotBackendError,
    URLValidationError,
)


class BackendRouteError(APIError):
    """Base class for backend route errors with an explicit category."""

    category = "backend"

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: int | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code, details=details)


class ClientInputError(BackendRouteError):
    """Client payload, form, or validation failure."""

    category = "client_input"

    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        code: int | str | None = None,
        details: dict[str, Any] | None = None,
        field: str | None = None,
    ) -> None:
        merged_details = dict(details or {})
        if field is not None:
            merged_details.setdefault("field", field)
        effective_details = merged_details or None
        super().__init__(
            message,
            status=status,
            code=code,
            details=effective_details,
        )


class ResourceLookupError(BackendRouteError):
    """Requested server-side resource could not be resolved."""

    category = "resource_lookup"

    def __init__(
        self,
        message: str,
        *,
        status: int = 404,
        code: int | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code, details=details)


class ConflictRouteError(BackendRouteError):
    """Request conflicts with current server state."""

    category = "conflict"

    def __init__(
        self,
        message: str,
        *,
        status: int = 409,
        code: int | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code, details=details)


class UnsupportedMediaTypeRouteError(BackendRouteError):
    """Request body/content type is unsupported."""

    category = "unsupported_media_type"

    def __init__(
        self,
        message: str = "Unsupported media type",
        *,
        code: int | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status=415, code=code, details=details)


class ServiceUnavailableRouteError(BackendRouteError):
    """Something the request needs is not running or not responding."""

    category = "unavailable"

    def __init__(
        self,
        message: str,
        *,
        status: int = 503,
        code: int | str | None = "backend_unavailable",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code, details=details)


class OperationFailedError(BackendRouteError):
    """Backend operation reported failure without throwing."""

    category = "operation_failed"

    def __init__(
        self,
        message: str,
        *,
        status: int = 500,
        code: int | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code, details=details)


class InternalOperationError(BackendRouteError):
    """Unexpected backend failure surfaced through the canonical JSON envelope."""

    category = "internal"

    def __init__(
        self,
        context: str,
        *,
        message: str = "An internal error occurred",
        status: int = 500,
        code: int | str | None = "internal_error",
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details: dict[str, Any] = {"context": context}
        if hint is not None:
            merged_details["hint"] = hint
        if details:
            merged_details.update(details)
        super().__init__(message, status=status, code=code, details=merged_details)


#: Response text for the domain errors. Module constants, like the other
#: messages below, so no exception text reaches a response body (CodeQL
#: ``py/stack-trace-exposure``).
REFRESH_TASK_UNAVAILABLE_MSG = RefreshTaskUnavailable.default_message
REFRESH_LOOP_BUSY_MSG = RefreshLoopBusy.default_message
PLUGIN_NOT_FOUND_MSG = PluginNotFound.default_message
PLUGIN_RENDER_FAILED_MSG = PluginRenderFailed.default_message


def route_error_for(err: BaseException) -> BackendRouteError | None:
    """Return the route error for an expected failure, or None for a crash.

    This is the one place that decides what each known failure from the
    refresh loop or a plugin render means over HTTP, so a failure gets the
    same status and code on every route that can hit it.
    """
    if isinstance(err, BlackoutActiveError):
        return ConflictRouteError(BLOCKED_MESSAGE, code="blackout_active")
    if isinstance(err, RefreshTaskUnavailable):
        return ServiceUnavailableRouteError(
            REFRESH_TASK_UNAVAILABLE_MSG, code="refresh_task_unavailable"
        )
    if isinstance(err, RefreshLoopBusy):
        return ServiceUnavailableRouteError(
            REFRESH_LOOP_BUSY_MSG, code="refresh_loop_busy"
        )
    if isinstance(err, PluginNotFound):
        return ResourceLookupError(
            PLUGIN_NOT_FOUND_MSG, status=404, code="plugin_not_found"
        )
    if isinstance(err, PluginRenderFailed):
        return _render_failed_route_error(err)
    if isinstance(err, URLValidationError):
        return ClientInputError(
            err.safe_message(), status=422, code="validation_error", field="url"
        )
    if isinstance(err, ProviderReportedPluginError):
        return ClientInputError(err.safe_message(), code="provider_rejected")
    if isinstance(err, ScreenshotBackendError):
        return ServiceUnavailableRouteError(SCREENSHOT_BACKEND_UNAVAILABLE_MSG)
    if isinstance(err, TimeoutError):
        return ServiceUnavailableRouteError(
            MANUAL_UPDATE_TIMEOUT_MSG, status=504, code="manual_update_timeout"
        )
    return None


def _render_failed_route_error(err: PluginRenderFailed) -> BackendRouteError:
    """400 ``plugin_error``, unless the plugin's error has its own answer.

    A rejected URL, a provider refusal or the screenshot backend being down
    are ``RuntimeError`` subclasses with answers of their own, so the cause
    is mapped first.
    """
    cause = err.__cause__
    if cause is not None and not isinstance(cause, PluginRenderFailed):
        mapped = route_error_for(cause)
        if mapped is not None:
            return mapped
    return ClientInputError(PLUGIN_RENDER_FAILED_MSG, code="plugin_error")


@contextmanager
def mapped_render_errors(
    context: str, *, logger: logging.Logger | None = None
) -> Iterator[None]:
    """Re-raise known failures from a render or refresh as their route error.

    Wrap the call that renders or asks the refresh loop to render. Anything
    :func:`route_error_for` does not recognise propagates unchanged.
    """
    try:
        yield
    except APIError:
        raise
    except Exception as err:
        mapped = route_error_for(err)
        if mapped is None:
            raise
        if logger is not None:
            logger.warning("%s: %s", context, mapped.code)
        raise mapped from err


@contextmanager
def route_error_boundary(
    context: str,
    *,
    logger: logging.Logger | None = None,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Wrap a route body and convert unexpected exceptions to InternalOperationError."""

    try:
        yield
    except APIError:
        raise
    except Exception as err:
        # Blackout and a stopped refresh loop are expected states, not
        # crashes, so every route reports them with their own status.
        mapped = route_error_for(err) if isinstance(err, DomainError) else None
        if mapped is not None:
            raise mapped from err
        if logger is not None:
            logger.exception("%s", context)
        raise InternalOperationError(
            context,
            hint=hint,
            details=details,
        ) from err

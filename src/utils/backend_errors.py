"""Typed backend route errors and a shared boundary for JSON handlers."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from utils.http_utils import APIError


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
        if logger is not None:
            logger.exception("%s", context)
        raise InternalOperationError(
            context,
            hint=hint,
            details=details,
        ) from err

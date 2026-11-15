"""The structured error the service workflows return instead of raising."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkflowError:
    """Structured error returned by service workflows."""

    message: str
    status: int = 400
    code: str = "validation_error"
    field: str | None = None
    details: dict[str, Any] | None = None

    def as_json_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments compatible with ``utils.http_utils.json_error``."""
        payload: dict[str, Any] = {"status": self.status, "code": self.code}
        details: dict[str, Any] = dict(self.details or {})
        if self.field is not None:
            details.setdefault("field", self.field)
        if details:
            payload["details"] = details
        return payload

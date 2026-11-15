"""The structured error the service workflows return instead of raising."""

from __future__ import annotations

from dataclasses import dataclass

from utils.json_types import JsonObject


@dataclass(frozen=True, slots=True)
class WorkflowError:
    """Structured error returned by service workflows."""

    message: str
    status: int = 400
    code: str = "validation_error"
    field: str | None = None
    details: JsonObject | None = None

    def as_json_kwargs(self) -> JsonObject:
        """Return keyword arguments compatible with ``utils.api_responses.json_error``."""
        payload: JsonObject = {"status": self.status, "code": self.code}
        details: JsonObject = dict(self.details or {})
        if self.field is not None:
            details.setdefault("field", self.field)
        if details:
            payload["details"] = details
        return payload

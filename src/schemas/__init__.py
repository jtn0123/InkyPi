"""Response schema TypedDicts for JSON API endpoints.

These schemas describe the shape of responses returned by high-traffic Flask
routes. They exist so contract tests can assert the UI/backend contract and
so mypy can type-check the producing route handlers.

Schemas are intentionally conservative: required keys are the ones the
current UI depends on, and ``total=False`` schemas describe payloads whose
keys are all optional in practice.
"""

from __future__ import annotations

from .responses import (
    ActionMetrics,
    BenchmarksSummaryResponse,
    HealthPluginsResponse,
    HealthSystemResponse,
    HistoryStorageResponse,
    IsolationResponse,
    MetricsSuccessResponse,
    NextUpResponse,
    RefreshInfoResponse,
    RefreshStatsResponse,
    RefreshStatsWindow,
    RollbackControlResponse,
    SaveApiKeysResponse,
    SuccessMessageResponse,
    SuccessMessageWarningResponse,
    SuccessResponse,
    TopFailingEntry,
    UpdateControlResponse,
    UptimeResponse,
    VersionInfoResponse,
)

__all__ = [
    "ActionMetrics",
    "BenchmarksSummaryResponse",
    "HealthPluginsResponse",
    "HealthSystemResponse",
    "HistoryStorageResponse",
    "IsolationResponse",
    "MetricsSuccessResponse",
    "NextUpResponse",
    "RefreshInfoResponse",
    "RefreshStatsResponse",
    "RollbackControlResponse",
    "SaveApiKeysResponse",
    "SuccessMessageResponse",
    "SuccessMessageWarningResponse",
    "SuccessResponse",
    "RefreshStatsWindow",
    "TopFailingEntry",
    "UptimeResponse",
    "UpdateControlResponse",
    "VersionInfoResponse",
]

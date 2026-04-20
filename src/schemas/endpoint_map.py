"""Mapping of Flask endpoint names to their canonical TypedDict response shape.

The dev-mode response-schema validator middleware (JTN-664) looks up
``flask.request.endpoint`` in this map to decide whether to validate a
response. Keys are ``<blueprint_name>.<view_function_name>`` — the exact
string Flask returns from ``request.endpoint`` — NOT URL paths.

Only endpoints whose successful response shape is pinned down by a TypedDict
in ``schemas.responses`` are listed here. Routes that return non-JSON or
whose successful payload shape varies by method are intentionally omitted; the
middleware further guards on ``response.mimetype == 'application/json'``.
"""

from __future__ import annotations

from schemas.responses import (
    BenchmarksPluginsResponse,
    BenchmarksSummaryResponse,
    DiagnosticsResponse,
    HealthPluginsResponse,
    HealthSystemResponse,
    HistoryStorageResponse,
    IsolationResponse,
    JobStatusResponse,
    MetricsSuccessResponse,
    NextUpResponse,
    RefreshInfoResponse,
    RefreshStatsResponse,
    RollbackControlResponse,
    SaveApiKeysResponse,
    SuccessMessageResponse,
    SuccessMessageWarningResponse,
    SuccessResponse,
    UpdateControlResponse,
    UptimeResponse,
    VersionInfoResponse,
)

# Endpoint name -> TypedDict schema class.
#
# Verified empirically: each value is the ``blueprint_name.view_function_name``
# string Flask reports via ``request.endpoint`` for the corresponding route.
ENDPOINT_SCHEMAS: dict[str, type] = {
    "version_info.api_version_info": VersionInfoResponse,
    "version_info.api_uptime": UptimeResponse,
    "main.refresh_info": RefreshInfoResponse,
    "main.next_up": NextUpResponse,
    "main.save_plugin_order": SuccessResponse,
    "main.display_next": MetricsSuccessResponse,
    "stats.refresh_stats": RefreshStatsResponse,
    "settings.health_system": HealthSystemResponse,
    "settings.health_plugins": HealthPluginsResponse,
    "settings.start_update": UpdateControlResponse,
    "settings.start_rollback": RollbackControlResponse,
    "settings.benchmarks_summary": BenchmarksSummaryResponse,
    "settings.benchmarks_plugins": BenchmarksPluginsResponse,
    "settings.safe_reset": SuccessMessageResponse,
    "settings.save_api_keys": SaveApiKeysResponse,
    "settings.delete_api_key": SuccessMessageResponse,
    "settings.save_settings": SuccessMessageResponse,
    "diagnostics.api_diagnostics": DiagnosticsResponse,
    "playlist.create_playlist": SuccessMessageWarningResponse,
    "playlist.update_playlist": SuccessMessageWarningResponse,
    "playlist.delete_playlist": SuccessMessageResponse,
    "playlist.update_device_cycle": SuccessMessageResponse,
    "playlist.reorder_plugins": SuccessMessageResponse,
    "playlist.display_next_in_playlist": MetricsSuccessResponse,
    "plugin.job_status": JobStatusResponse,
    "settings.plugin_isolation": IsolationResponse,
    "history.history_redisplay": SuccessMessageResponse,
    "history.history_delete": SuccessMessageResponse,
    "history.history_clear": SuccessMessageResponse,
    "history.history_storage": HistoryStorageResponse,
}

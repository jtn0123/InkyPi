"""Mapping of Flask endpoint names to their canonical TypedDict response shape.

The dev-mode response-schema validator middleware (JTN-664) looks up
``flask.request.endpoint`` in this map to decide whether to validate a
response. Keys are ``<blueprint_name>.<view_function_name>`` — the exact
string Flask returns from ``request.endpoint`` — NOT URL paths.

Only endpoints whose successful response shape is pinned down by a TypedDict
in ``schemas.responses`` are listed here. Routes that return non-JSON,
envelope-only errors, or method-dependent payloads (e.g. POST/DELETE on
``/settings/isolation``) are intentionally omitted; the middleware further
guards on ``response.mimetype == 'application/json'``.
"""

from __future__ import annotations

from schemas.responses import (
    HealthPluginsResponse,
    HealthSystemResponse,
    HistoryStorageResponse,
    IsolationResponse,
    NextUpResponse,
    RefreshInfoResponse,
    RefreshStatsResponse,
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
    "stats.refresh_stats": RefreshStatsResponse,
    "settings.health_system": HealthSystemResponse,
    "settings.health_plugins": HealthPluginsResponse,
    "settings.plugin_isolation": IsolationResponse,
    "history.history_storage": HistoryStorageResponse,
}

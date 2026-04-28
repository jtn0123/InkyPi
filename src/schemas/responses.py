"""TypedDict response shapes for high-traffic JSON endpoints.

These describe the canonical successful JSON responses the UI consumes.
They are used by:

* ``tests/contract/test_response_shapes.py`` to assert routes keep returning
  the documented shape (prevents silent drift breaking the UI).
* ``mypy`` as optional producer-side annotations.

Design notes
------------
* ``total=False`` is used when every field is optional in practice (e.g. the
  ``/next-up`` endpoint returns ``{}`` when no plugin is scheduled).
* Envelope fields (``success``, ``request_id``, ``message``) are included as
  optional when the endpoint wraps its payload with ``json_success``; see
  ``utils.http_utils.json_success``.
"""

from __future__ import annotations

from typing import Any, TypedDict

# ---------------------------------------------------------------------------
# Common mutating JSON success envelopes
# ---------------------------------------------------------------------------


class SuccessResponse(TypedDict):
    """Base envelope returned by ``json_success``."""

    success: bool


class ActionMetricStep(TypedDict, total=False):
    """One optional progress/metrics step emitted by render/update actions."""

    name: str
    description: str
    status: str
    elapsed_ms: int
    error_message: str
    substeps: list[str]


class ActionMetrics(TypedDict, total=False):
    """Timing metrics attached to display/update success responses."""

    request_ms: int | None
    generate_ms: int | None
    preprocess_ms: int | None
    display_ms: int | None
    steps: list[ActionMetricStep]


# ---------------------------------------------------------------------------
# GET /api/version/info
# ---------------------------------------------------------------------------


class VersionInfoResponse(TypedDict):
    """Response body for ``GET /api/version/info`` (``blueprints.version_info``)."""

    version: str
    git_sha: str
    git_branch: str
    build_time: str
    python_version: str


# ---------------------------------------------------------------------------
# GET /api/uptime
# ---------------------------------------------------------------------------


class UptimeResponse(TypedDict):
    """Response body for ``GET /api/uptime``.

    ``system_uptime_seconds`` is ``None`` off-Linux; ``process_uptime_seconds``
    is a float (time.monotonic delta).
    """

    process_uptime_seconds: float
    system_uptime_seconds: int | None
    process_started_at: str


# ---------------------------------------------------------------------------
# GET /refresh-info
# ---------------------------------------------------------------------------


class RefreshInfoResponse(TypedDict, total=False):
    """Response body for ``GET /refresh-info``.

    All fields are optional because the route falls back to ``{}`` when no
    refresh has ever succeeded (see ``blueprints.main.refresh_info``).
    """

    refresh_time: str | None
    image_hash: int | str | None
    refresh_type: str | None
    plugin_id: str | None
    playlist: str
    plugin_instance: str
    plugin_instance_label: str
    request_ms: int
    display_ms: int
    generate_ms: int
    preprocess_ms: int
    used_cached: bool
    benchmark_id: str
    plugin_meta: dict[str, Any]


# ---------------------------------------------------------------------------
# GET /next-up
# ---------------------------------------------------------------------------


class NextUpResponse(TypedDict, total=False):
    """Response body for ``GET /next-up``.

    When nothing is scheduled the route returns an empty ``{}``. When a plugin
    is scheduled, ``playlist``, ``plugin_id`` and ``plugin_instance`` are all
    populated together.
    """

    playlist: str
    plugin_id: str
    plugin_instance: str
    plugin_instance_label: str


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------


class TopFailingEntry(TypedDict):
    """One entry of ``RefreshStatsWindow.top_failing``."""

    plugin: str
    count: int


class RefreshStatsWindow(TypedDict):
    """Single-window payload from ``utils.refresh_stats.compute_stats``."""

    total: int
    success: int
    failure: int
    success_rate: float
    p50_duration_ms: int
    p95_duration_ms: int
    top_failing: list[TopFailingEntry]


class RefreshStatsResponse(TypedDict):
    """Response body for ``GET /api/stats``."""

    last_1h: RefreshStatsWindow
    last_24h: RefreshStatsWindow
    last_7d: RefreshStatsWindow


# ---------------------------------------------------------------------------
# GET /api/health/system
# ---------------------------------------------------------------------------


class HealthSystemResponse(TypedDict, total=False):
    """Response body for ``GET /api/health/system`` (wraps ``json_success``)."""

    success: bool
    request_id: str
    cpu_percent: float | None
    memory_percent: float | None
    disk_percent: float | None
    disk_free_gb: float | None
    disk_total_gb: float | None
    uptime_seconds: int | None


# ---------------------------------------------------------------------------
# GET /api/health/plugins
# ---------------------------------------------------------------------------


class HealthPluginsResponse(TypedDict, total=False):
    """Response body for ``GET /api/health/plugins`` (wraps ``json_success``).

    ``items`` maps plugin_id -> arbitrary health snapshot dict.
    """

    success: bool
    request_id: str
    items: dict[str, Any]


# ---------------------------------------------------------------------------
# Shared success envelopes for mutating UI-facing routes
# ---------------------------------------------------------------------------


class SuccessMessageResponse(TypedDict, total=False):
    """Canonical ``json_success`` envelope with a message."""

    success: bool
    request_id: str
    message: str


class SuccessMessageWarningResponse(SuccessMessageResponse, total=False):
    """Message envelope with an optional soft warning."""

    warning: str


class UpdateControlResponse(SuccessMessageResponse, total=False):
    """Update / rollback launch envelope returned by settings actions."""

    running: bool
    unit: str | None


class RollbackControlResponse(UpdateControlResponse, total=False):
    """Rollback launch envelope with the rollback target version."""

    target_version: str


class MetricsSuccessResponse(SuccessMessageResponse, total=False):
    """Success envelope that also includes timing metrics."""

    metrics: ActionMetrics


class SaveApiKeysResponse(SuccessMessageResponse, total=False):
    """Success response for ``POST /settings/save_api_keys``."""

    updated: list[str]
    skipped_placeholder: list[str]


# ---------------------------------------------------------------------------
# GET /settings/isolation
# ---------------------------------------------------------------------------


class IsolationResponse(TypedDict, total=False):
    """Response body for ``GET /settings/isolation`` (wraps ``json_success``)."""

    success: bool
    request_id: str
    isolated_plugins: list[str]


# ---------------------------------------------------------------------------
# GET /history/storage
# ---------------------------------------------------------------------------


class HistoryStorageResponse(TypedDict):
    """Response body for ``GET /history/storage``.

    ``pct_free`` is ``None`` only when ``total_gb`` is 0 (should never happen
    on a real filesystem).
    """

    free_gb: float
    total_gb: float
    used_gb: float
    pct_free: float | None


# ---------------------------------------------------------------------------
# GET /api/benchmarks/summary
# ---------------------------------------------------------------------------


class BenchmarksSummaryResponse(TypedDict, total=False):
    """Response body for ``GET /api/benchmarks/summary`` (wraps ``json_success``).

    Only present when the benchmarks feature flag is enabled — otherwise the
    route returns a 404 error envelope. ``summary`` maps stage name to
    ``{"p50": int, "p95": int}``.
    """

    success: bool
    request_id: str
    count: int
    summary: dict[str, dict[str, int | None]]


class BenchmarksPluginEntry(TypedDict):
    """One plugin aggregate row from ``GET /api/benchmarks/plugins``."""

    plugin_id: str
    runs: int
    request_avg: int | None
    generate_avg: int | None
    display_avg: int | None


class BenchmarksPluginsResponse(TypedDict, total=False):
    """Response body for ``GET /api/benchmarks/plugins`` (wraps ``json_success``)."""

    success: bool
    request_id: str
    items: list[BenchmarksPluginEntry]


class BenchmarksRefreshEntry(TypedDict):
    """One recent refresh row from ``GET /api/benchmarks/refreshes``."""

    id: int
    ts: float
    refresh_id: str
    plugin_id: str | None
    instance: str | None
    playlist: str | None
    used_cached: int | None
    request_ms: int | None
    generate_ms: int | None
    preprocess_ms: int | None
    display_ms: int | None


class BenchmarksRefreshesResponse(TypedDict, total=False):
    """Response body for ``GET /api/benchmarks/refreshes``."""

    success: bool
    request_id: str
    items: list[BenchmarksRefreshEntry]
    next_cursor: str | None


class BenchmarksStageEntry(TypedDict):
    """One stage event from ``GET /api/benchmarks/stages``."""

    id: int
    ts: float
    stage: str
    duration_ms: int | None
    extra_json: str | None


class BenchmarksStagesResponse(TypedDict, total=False):
    """Response body for ``GET /api/benchmarks/stages``."""

    success: bool
    request_id: str
    items: list[BenchmarksStageEntry]


class JobStatusResult(TypedDict, total=False):
    """Async ``/update_now`` job result payload returned by ``/api/job/<job_id>``."""

    success: bool
    message: str
    metrics: dict[str, Any]


class JobStatusResponse(TypedDict, total=False):
    """Response body for ``GET /api/job/<job_id>``."""

    status: str
    result: JobStatusResult
    error: str


class DiagnosticsMemory(TypedDict):
    """``memory`` object in ``GET /api/diagnostics``."""

    total_mb: int | None
    used_mb: int | None
    pct: float | None


class DiagnosticsDisk(TypedDict):
    """``disk`` object in ``GET /api/diagnostics``."""

    total_mb: int | None
    used_mb: int | None
    pct: float | None
    path: str


class DiagnosticsRefreshTask(TypedDict):
    """``refresh_task`` object in ``GET /api/diagnostics``."""

    running: bool
    last_run_ts: str | None
    last_error: str | None


class DiagnosticsClientLogErrors(TypedDict):
    """``recent_client_log_errors`` object in ``GET /api/diagnostics``."""

    count_5m: int
    warn_count_5m: int
    last_error_ts: float | None
    window_seconds: int


class DiagnosticsResponse(TypedDict):
    """Response body for ``GET /api/diagnostics``."""

    ts: str
    version: str
    prev_version: str | None
    uptime_s: int | None
    memory: DiagnosticsMemory
    disk: DiagnosticsDisk
    refresh_task: DiagnosticsRefreshTask
    plugin_health: dict[str, str]
    log_tail_100: list[str]
    last_update_failure: Any | None
    recent_client_log_errors: DiagnosticsClientLogErrors

"""refresh_stats — compute rolling refresh aggregates from history sidecar files.

Reads JSON sidecar files written alongside PNG history images and produces
window-based statistics (1h, 24h, 7d).  Results are cached in-process for
60 seconds to avoid repeated directory scans on high-frequency polling.

Sidecar schema (subset used here)
----------------------------------
{
    "status": "success" | "failure",
    "duration_ms": <int>,          # total refresh wall-clock time
    "plugin_id": "<str>",          # plugin that generated the image
    "timestamp": <float>,          # Unix epoch of the refresh
}

Any field may be absent; absent fields cause that sidecar to be excluded from
the relevant aggregate (e.g. a missing ``duration_ms`` does not affect totals).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache — one entry per (history_dir, window_seconds) pair
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 60

RefreshStatsRecord = dict[str, Any]
RefreshStatsResult = dict[str, Any]

_cache: dict[tuple[str, int], tuple[float, RefreshStatsResult]] = {}


def _now() -> float:
    """Return the current time as a Unix timestamp (mockable in tests)."""
    return time.time()


def _percentile(sorted_values: list[float], pct: float) -> int:
    """Return the *pct*-th percentile of *sorted_values* (0-100), or 0 if empty."""
    if not sorted_values:
        return 0
    idx = max(0, min(len(sorted_values) - 1, int(len(sorted_values) * pct / 100)))
    return int(sorted_values[idx])


def _load_sidecars(history_dir: str, since: float) -> list[RefreshStatsRecord]:
    """Read all JSON sidecar files from *history_dir* whose timestamp >= *since*.

    Only reads files that end with ``.json``.  Malformed or unreadable files are
    silently skipped.
    """
    records: list[RefreshStatsRecord] = []
    try:
        names = os.listdir(history_dir)
    except OSError:
        logger.debug("refresh_stats: cannot list %s", history_dir)
        return records

    for name in names:
        if not name.lower().endswith(".json"):
            continue
        full_path = os.path.join(history_dir, name)
        if os.path.islink(full_path):
            continue
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            continue
        # Quick pre-filter on mtime before reading the file
        if mtime < since:
            continue
        try:
            with open(full_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        # Use explicit ``timestamp`` field when available, fall back to mtime
        ts = data.get("timestamp")
        if not isinstance(ts, int | float):
            ts = mtime
        if ts < since:
            continue
        records.append({**data, "_ts": float(ts)})

    return records


def _compute_window(records: list[RefreshStatsRecord]) -> RefreshStatsResult:
    """Build the stats dict for a pre-filtered list of sidecar records."""
    total = len(records)
    success = sum(1 for r in records if r.get("status") == "success")
    failure = total - success
    success_rate = (success / total) if total else 0.0

    durations = sorted(
        r["duration_ms"]
        for r in records
        if isinstance(r.get("duration_ms"), int | float)
    )

    p50 = _percentile(durations, 50)
    p95 = _percentile(durations, 95)

    # Top failing plugins — plugins that appear in failure records
    fail_counter: Counter[str] = Counter()
    for r in records:
        if r.get("status") == "failure":
            plugin = r.get("plugin_id") or r.get("plugin") or "unknown"
            fail_counter[plugin] += 1

    top_failing = [
        {"plugin": plugin, "count": count}
        for plugin, count in fail_counter.most_common(5)
    ]

    return {
        "total": total,
        "success": success,
        "failure": failure,
        "success_rate": round(success_rate, 4),
        "p50_duration_ms": p50,
        "p95_duration_ms": p95,
        "top_failing": top_failing,
    }


def compute_stats(history_dir: str, window_seconds: int) -> RefreshStatsResult:
    """Return refresh aggregates for the last *window_seconds* seconds.

    Results are cached for 60 seconds per (history_dir, window_seconds) pair.

    Returns
    -------
    dict with keys:
        total, success, failure, success_rate, p50_duration_ms,
        p95_duration_ms, top_failing
    """
    cache_key = (history_dir, window_seconds)
    now = _now()

    cached_at, cached_result = _cache.get(cache_key, (0.0, {}))
    if now - cached_at < _CACHE_TTL_SECONDS and cached_result:
        return cached_result

    since = now - window_seconds
    records = _load_sidecars(history_dir, since)
    result = _compute_window(records)

    _cache[cache_key] = (now, result)
    return result


def _clear_cache() -> None:
    """Evict all cached entries.  Intended for tests only."""
    _cache.clear()

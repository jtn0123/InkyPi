#!/usr/bin/env python3
"""Real-Pi nightly soak runner (JTN-733).

Connects to a running InkyPi instance and samples ``/api/diagnostics`` at a
fixed cadence for a configurable duration, then emits a JSON report covering
memory / disk trend, refresh-task failure rate, client-log error rate, and
the number of service restarts observed during the run.

The primary target is a self-hosted Raspberry Pi runner exercising a fixed
playlist of 5+ plugins on a 10-min cadence for 24 hours — catching slow
leaks, wedges, and refresh drift that CI (minute-scale) cannot. The script
is also runnable locally against any instance (``--duration 10m``).

Usage
-----

    # 30-second smoke test against a local dev server
    python scripts/soak_runner.py --duration 30s --host http://127.0.0.1:5000

    # Full 24h nightly (default) against a Pi on the LAN
    INKYPI_TOKEN=... python scripts/soak_runner.py --host http://inkypi.local

Report shape
------------

The JSON report written via ``--output`` has the following top-level keys:

* ``meta``   — host, duration, cadence, start/end ts, script version
* ``samples`` — list of raw per-sample snapshots (ts, memory, disk,
  refresh_task, recent_client_log_errors, uptime_s, version, fetch_ok,
  fetch_error)
* ``summary`` — aggregates: counts, rates, and linear-fit trend slopes
  for memory_pct / disk_pct so a slow leak shows up as a monotonic
  positive slope

See ``summarize_samples`` for the exact summary fields.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ``requests`` is already a runtime dep of InkyPi (see pyproject.toml). The
# test suite mocks HTTP and doesn't actually import this, so we keep the
# import lazy-friendly but at module top-level for normal invocation.
try:  # pragma: no cover — availability is environmental
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


SCRIPT_VERSION = "1"

# Default cadence: sample /api/diagnostics every 5 minutes.
DEFAULT_SAMPLE_INTERVAL_S = 300
# Default soak duration: 24 hours. Override via --duration.
DEFAULT_DURATION_S = 24 * 60 * 60
# Per-request timeout. The Pi can be slow; a wedge is 30s+.
DEFAULT_REQUEST_TIMEOUT_S = 30

logger = logging.getLogger("soak_runner")


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(value: str) -> int:
    """Parse ``30s`` / ``10m`` / ``24h`` / ``1d`` / bare seconds into int seconds.

    Raises ``ValueError`` on malformed input. The return is always >= 1.
    """
    if value is None:
        raise ValueError("duration is required")
    m = _DURATION_RE.match(str(value))
    if not m:
        raise ValueError(f"invalid duration: {value!r}")
    qty = float(m.group(1))
    unit = m.group(2).lower()
    seconds = qty * _UNIT_SECONDS[unit]
    if seconds < 1:
        raise ValueError(f"duration must be >= 1s (got {value!r})")
    return int(seconds)


# ---------------------------------------------------------------------------
# Sample record
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    """One ``/api/diagnostics`` probe result.

    ``fetch_ok=False`` means the HTTP call failed (timeout, connection refused,
    5xx, etc.) — these count as "service restart / wedge" data points. The
    remaining fields will be ``None`` in that case.
    """

    ts: str
    elapsed_s: float
    fetch_ok: bool
    fetch_error: str | None = None
    http_status: int | None = None
    version: str | None = None
    uptime_s: int | None = None
    memory_pct: float | None = None
    disk_pct: float | None = None
    refresh_running: bool | None = None
    refresh_last_error: str | None = None
    client_log_count_5m: int | None = None
    client_log_warn_count_5m: int | None = None
    plugin_health: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "elapsed_s": round(self.elapsed_s, 3),
            "fetch_ok": self.fetch_ok,
            "fetch_error": self.fetch_error,
            "http_status": self.http_status,
            "version": self.version,
            "uptime_s": self.uptime_s,
            "memory_pct": self.memory_pct,
            "disk_pct": self.disk_pct,
            "refresh_running": self.refresh_running,
            "refresh_last_error": self.refresh_last_error,
            "client_log_count_5m": self.client_log_count_5m,
            "client_log_warn_count_5m": self.client_log_warn_count_5m,
            "plugin_health": dict(self.plugin_health),
        }


# ---------------------------------------------------------------------------
# Diagnostics parsing
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_diagnostics_payload(
    payload: dict[str, Any] | None,
    *,
    elapsed_s: float,
    http_status: int | None,
) -> Sample:
    """Convert a ``/api/diagnostics`` JSON body into a :class:`Sample`.

    Unexpected / missing fields are tolerated — the sample still records
    whatever is parseable and leaves the rest as ``None``. This keeps the
    soak runner compatible with future diagnostics additions.
    """
    ts = datetime.now(UTC).isoformat()
    if not isinstance(payload, dict):
        return Sample(
            ts=ts,
            elapsed_s=elapsed_s,
            fetch_ok=False,
            fetch_error="non-dict payload",
            http_status=http_status,
        )

    memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    disk = payload.get("disk") if isinstance(payload.get("disk"), dict) else {}
    refresh = (
        payload.get("refresh_task")
        if isinstance(payload.get("refresh_task"), dict)
        else {}
    )
    client_log = (
        payload.get("recent_client_log_errors")
        if isinstance(payload.get("recent_client_log_errors"), dict)
        else {}
    )
    plugin_health_raw = payload.get("plugin_health")
    plugin_health: dict[str, str] = {}
    if isinstance(plugin_health_raw, dict):
        plugin_health = {
            k: v
            for k, v in plugin_health_raw.items()
            if isinstance(k, str) and isinstance(v, str)
        }

    return Sample(
        ts=ts,
        elapsed_s=elapsed_s,
        fetch_ok=True,
        fetch_error=None,
        http_status=http_status,
        version=(
            payload.get("version") if isinstance(payload.get("version"), str) else None
        ),
        uptime_s=_safe_int(payload.get("uptime_s")),
        memory_pct=_safe_float(memory.get("pct")),
        disk_pct=_safe_float(disk.get("pct")),
        refresh_running=bool(refresh.get("running")) if "running" in refresh else None,
        refresh_last_error=(
            refresh.get("last_error")
            if isinstance(refresh.get("last_error"), str)
            else None
        ),
        client_log_count_5m=_safe_int(client_log.get("count_5m")),
        client_log_warn_count_5m=_safe_int(client_log.get("warn_count_5m")),
        plugin_health=plugin_health,
    )


# ---------------------------------------------------------------------------
# Linear-fit trend summary
# ---------------------------------------------------------------------------


def _linear_fit_slope(
    xs: list[float], ys: list[float]
) -> tuple[float | None, float | None]:
    """Return (slope, intercept) from least-squares on (xs, ys).

    Returns ``(None, None)`` if fewer than 2 points or xs has zero variance
    (all samples at the same timestamp, which shouldn't happen in practice
    but is defensive). Slope units are ``delta-y per unit-x`` — in this
    runner x is seconds-since-start and y is percent, so slope is "percent
    per second". Multiply by 3600 for "percent per hour".
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return None, None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return None, None
    slope = num / den
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _trend_summary(samples: list[Sample], attr: str) -> dict[str, Any]:
    """Build a trend summary block for a single ``percent``-valued attribute.

    Includes the first/last/min/max values plus a linear-fit slope (per
    second AND per hour). The per-hour slope is the headline metric in the
    report — a slow leak over a 24h window should show up as a clear
    positive ``slope_per_hour``.
    """
    xs: list[float] = []
    ys: list[float] = []
    for s in samples:
        if not s.fetch_ok:
            continue
        v = getattr(s, attr)
        if v is None:
            continue
        xs.append(s.elapsed_s)
        ys.append(float(v))

    block: dict[str, Any] = {
        "n": len(ys),
        "first": ys[0] if ys else None,
        "last": ys[-1] if ys else None,
        "min": min(ys) if ys else None,
        "max": max(ys) if ys else None,
        "slope_per_second": None,
        "slope_per_hour": None,
    }
    slope, _ = _linear_fit_slope(xs, ys)
    if slope is not None:
        block["slope_per_second"] = slope
        block["slope_per_hour"] = slope * 3600.0
    return block


def _detect_restarts(samples: list[Sample]) -> int:
    """Count apparent service restarts across the sample window.

    A restart is inferred when ``uptime_s`` decreases between two successful
    samples — the box either rebooted or inkypi was restarted. Fetch
    failures are tracked separately as ``unreachable_samples`` because they
    may be transient network blips rather than a full restart.
    """
    restarts = 0
    prev_uptime: int | None = None
    for s in samples:
        if not s.fetch_ok or s.uptime_s is None:
            prev_uptime = None
            continue
        if prev_uptime is not None and s.uptime_s < prev_uptime:
            restarts += 1
        prev_uptime = s.uptime_s
    return restarts


def summarize_samples(samples: list[Sample]) -> dict[str, Any]:
    """Build the ``summary`` block of the soak report.

    Key fields:

    * ``total_samples`` / ``successful_samples`` / ``unreachable_samples``
    * ``unreachable_rate`` — fraction of samples where the HTTP call failed.
      A high rate suggests a wedge / crash-loop.
    * ``refresh_failure_rate`` — fraction of successful samples whose
      ``refresh_task.last_error`` is set.
    * ``client_log_error_total`` — sum of ``count_5m`` across samples. This
      double-counts overlapping 5-minute windows when cadence is < 5 min,
      but is a useful directional signal.
    * ``service_restarts`` — inferred from uptime regressions.
    * ``memory_pct_trend`` / ``disk_pct_trend`` — linear-fit blocks with
      ``slope_per_hour`` so reviewers can eyeball monotonic growth.
    """
    total = len(samples)
    ok = [s for s in samples if s.fetch_ok]
    unreachable = total - len(ok)
    refresh_failures = sum(1 for s in ok if s.refresh_last_error)
    client_log_error_total = sum((s.client_log_count_5m or 0) for s in ok)
    client_log_warn_total = sum((s.client_log_warn_count_5m or 0) for s in ok)

    return {
        "total_samples": total,
        "successful_samples": len(ok),
        "unreachable_samples": unreachable,
        "unreachable_rate": (unreachable / total) if total else 0.0,
        "refresh_failure_count": refresh_failures,
        "refresh_failure_rate": (refresh_failures / len(ok)) if ok else 0.0,
        "client_log_error_total": client_log_error_total,
        "client_log_warn_total": client_log_warn_total,
        "service_restarts": _detect_restarts(samples),
        "memory_pct_trend": _trend_summary(samples, "memory_pct"),
        "disk_pct_trend": _trend_summary(samples, "disk_pct"),
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_report(
    *,
    host: str,
    duration_s: int,
    interval_s: int,
    samples: list[Sample],
    started_at: str,
    ended_at: str,
) -> dict[str, Any]:
    """Return the full JSON-serializable soak report."""
    return {
        "meta": {
            "script_version": SCRIPT_VERSION,
            "host": host,
            "duration_s": duration_s,
            "sample_interval_s": interval_s,
            "started_at": started_at,
            "ended_at": ended_at,
            "sample_count": len(samples),
        },
        "samples": [s.to_dict() for s in samples],
        "summary": summarize_samples(samples),
    }


# ---------------------------------------------------------------------------
# Sampling loop
# ---------------------------------------------------------------------------


def _fetch_once(
    session: Any,
    url: str,
    *,
    headers: dict[str, str],
    timeout_s: float,
) -> tuple[dict[str, Any] | None, int | None, str | None, float]:
    """Fetch ``url`` once. Returns (payload, http_status, error, elapsed_s)."""
    t0 = time.monotonic()
    try:
        resp = session.get(url, headers=headers, timeout=timeout_s)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return None, None, f"{type(exc).__name__}: {exc}", elapsed

    elapsed = time.monotonic() - t0
    status = resp.status_code
    if status != 200:
        return None, status, f"HTTP {status}", elapsed
    try:
        return resp.json(), status, None, elapsed
    except Exception as exc:
        return None, status, f"json decode: {exc}", elapsed


def run_soak(
    *,
    host: str,
    duration_s: int,
    interval_s: int,
    token: str | None = None,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    session: Any = None,
    now: Any = None,
    sleep: Any = None,
) -> list[Sample]:
    """Run the sampling loop and return the collected samples.

    Parameters ``session`` / ``now`` / ``sleep`` are injection seams used by
    the unit tests; at runtime they default to ``requests.Session`` /
    ``time.monotonic`` / ``time.sleep``.
    """
    if session is None:
        if requests is None:
            raise RuntimeError(
                "The 'requests' package is required to run the soak loop. "
                "Install it or inject a session."
            )
        session = requests.Session()
    if now is None:
        now = time.monotonic
    if sleep is None:
        sleep = time.sleep

    url = host.rstrip("/") + "/api/diagnostics"
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        # The diagnostics endpoint rides on InkyPi's PIN auth gate — a
        # bearer token is not the actual auth mechanism in-tree, but most
        # reverse proxies in front of a real Pi deployment accept one,
        # and we forward X-InkyPi-Token for future hook-up.
        headers["Authorization"] = f"Bearer {token}"
        headers["X-InkyPi-Token"] = token

    samples: list[Sample] = []
    start = now()
    deadline = start + duration_s
    next_tick = start

    while True:
        t = now()
        if t >= deadline:
            break

        if t < next_tick:
            sleep(min(next_tick - t, 1.0))
            continue

        elapsed_since_start = t - start
        payload, status, err, req_elapsed = _fetch_once(
            session, url, headers=headers, timeout_s=request_timeout_s
        )
        if payload is not None:
            sample = parse_diagnostics_payload(
                payload, elapsed_s=elapsed_since_start, http_status=status
            )
        else:
            sample = Sample(
                ts=datetime.now(UTC).isoformat(),
                elapsed_s=elapsed_since_start,
                fetch_ok=False,
                fetch_error=err,
                http_status=status,
            )
        samples.append(sample)
        logger.info(
            "sample %d t=%.1fs ok=%s mem=%s disk=%s err=%s",
            len(samples),
            elapsed_since_start,
            sample.fetch_ok,
            sample.memory_pct,
            sample.disk_pct,
            sample.fetch_error,
        )

        next_tick += interval_s
        # If we blew through the next tick (slow request, long backoff), fast-
        # forward so we don't spin sampling back-to-back.
        if next_tick <= now():
            next_tick = now() + interval_s

    return samples


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _default_output_path() -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"soak-report-{ts}.json")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="InkyPi real-Pi soak runner (JTN-733).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("INKYPI_HOST", "http://127.0.0.1:8080"),
        help="Base URL of the InkyPi instance (default: $INKYPI_HOST or http://127.0.0.1:8080).",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("INKYPI_TOKEN"),
        help="Optional bearer token forwarded in Authorization + X-InkyPi-Token headers.",
    )
    parser.add_argument(
        "--duration",
        default="24h",
        help="Total soak duration (e.g. 30s, 10m, 24h). Default: 24h.",
    )
    parser.add_argument(
        "--interval",
        default="5m",
        help="Sample cadence (e.g. 1m, 5m). Default: 5m.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_S,
        help="Per-request timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write the JSON report (default: soak-report-<utc>.json in cwd).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log each sample at INFO level (default: WARNING).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        duration_s = parse_duration(args.duration)
        interval_s = parse_duration(args.interval)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if interval_s > duration_s:
        print(
            f"error: --interval ({interval_s}s) must be <= --duration ({duration_s}s)",
            file=sys.stderr,
        )
        return 2

    output_path = args.output or _default_output_path()
    started_at = datetime.now(UTC).isoformat()

    logger.warning(
        "soak starting: host=%s duration=%ds interval=%ds output=%s",
        args.host,
        duration_s,
        interval_s,
        output_path,
    )

    samples = run_soak(
        host=args.host,
        duration_s=duration_s,
        interval_s=interval_s,
        token=args.token,
        request_timeout_s=args.timeout,
    )

    ended_at = datetime.now(UTC).isoformat()
    report = build_report(
        host=args.host,
        duration_s=duration_s,
        interval_s=interval_s,
        samples=samples,
        started_at=started_at,
        ended_at=ended_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    summary = report["summary"]
    logger.warning(
        "soak complete: %d samples (%d ok, %d unreachable), restarts=%d, "
        "refresh_failure_rate=%.3f, memory_slope_per_hour=%s",
        summary["total_samples"],
        summary["successful_samples"],
        summary["unreachable_samples"],
        summary["service_restarts"],
        summary["refresh_failure_rate"],
        summary["memory_pct_trend"].get("slope_per_hour"),
    )
    print(str(output_path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Blueprint: POST /api/client-log — receive and log browser console messages (JTN-481).

Accepts JSON reports from the console.warn/error shim in client_log_reporter.js,
validates the schema, caps field sizes, and logs as WARNING so the server-side
SecretRedactionFilter (JTN-364) strips any secrets before they reach disk.

Only active when the page opts in via:
    <meta name="client-log-enabled" content="1">

Rate-limited per remote IP using TokenBucket. In production the bucket is sized
at capacity=60, refill=10/s (JTN-711) so a burst of errors from a broken page
is not silently dropped. Each POST — whether it carries a single entry or a
batch array — consumes exactly one token.

Payload shapes (both accepted):
    1. Single object: ``{"level": "warn", "message": "..."}``
    2. Batch array:   ``[{"level": "warn", ...}, {"level": "error", ...}]``
       Batch size is capped at ``_BATCH_MAX`` entries; oversized batches are
       rejected with 400.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from typing import Any

from flask import Blueprint, Response

from utils.client_endpoint import enforce_size_and_rate
from utils.form_utils import sanitize_log_field
from utils.http_utils import json_error, reissue_json_error
from utils.rate_limit import TokenBucket

logger = logging.getLogger(__name__)

client_log_bp = Blueprint("client_log", __name__)

# ---------------------------------------------------------------------------
# Test-only capture hook (JTN-680).
#
# When the environment variable ``INKYPI_TEST_CAPTURE_CLIENT_LOG`` is set to
# ``1``/``true``/``yes`` (checked per request), every successfully-validated
# client-log report is appended to a process-wide list below so Playwright
# tests can assert no unexpected ``console.warn``/``console.error`` reached
# the server during the test. A lock protects list access because the Flask
# live_server fixture is threaded.
#
# The env var is consulted *only* when a request comes in; when it is unset
# the handler behaves bit-identical to the pre-JTN-680 implementation.
# ---------------------------------------------------------------------------
_TEST_CAPTURE_ENV = "INKYPI_TEST_CAPTURE_CLIENT_LOG"
_CAPTURE_TRUE_VALUES = frozenset({"1", "true", "yes"})

_captured_reports: list[dict[str, object]] = []
_captured_lock = threading.Lock()


def _capture_enabled() -> bool:
    raw = os.environ.get(_TEST_CAPTURE_ENV, "")
    return raw.strip().lower() in _CAPTURE_TRUE_VALUES


def get_captured_reports() -> list[dict[str, object]]:
    """Return a shallow copy of the process-wide captured-report list.

    Returns an empty list if capture is disabled or nothing has been posted.
    """
    with _captured_lock:
        return list(_captured_reports)


def reset_captured_reports() -> None:
    """Clear the process-wide list of captured client-log reports."""
    with _captured_lock:
        _captured_reports.clear()


# ---------------------------------------------------------------------------
# Recent-error ring buffer (JTN-709).
#
# The /api/diagnostics endpoint exposes a "recent_client_log_errors" summary so
# the in-app status badge can flip to warning/error when the browser reports
# problems. We keep a small bounded deque of ``(timestamp, level)`` pairs —
# enough to answer "how many errors in the last 5 minutes?" without growing
# unboundedly on a broken page. In-memory only; disk persistence would leak
# across restarts for no added UX value.
# ---------------------------------------------------------------------------
_RECENT_BUFFER_MAX = 100
_recent_errors: deque[tuple[float, str]] = deque(maxlen=_RECENT_BUFFER_MAX)
_recent_lock = threading.Lock()


def _record_recent(level: str) -> None:
    """Append ``(now, level)`` to the recent-errors ring buffer."""
    with _recent_lock:
        _recent_errors.append((time.time(), level))


def get_recent_error_summary(
    now: float | None = None, *, window_seconds: int = 300
) -> dict[str, Any]:
    """Return a summary of recent client-log entries for diagnostics.

    Shape::

        {
          "count_5m": int,           # entries with level == "error" in window
          "warn_count_5m": int,      # entries with level == "warn" in window
          "last_error_ts": float|None,  # epoch seconds of most recent "error"
          "window_seconds": int
        }

    The window defaults to 300s (5 minutes). ``last_error_ts`` is the epoch
    timestamp of the most recent *error* (not warn) entry in the buffer, or
    None if the buffer contains no error entries at all.
    """
    cutoff = (time.time() if now is None else now) - float(window_seconds)
    err_count = 0
    warn_count = 0
    last_error_ts: float | None = None
    with _recent_lock:
        for ts, level in _recent_errors:
            if level == "error" and (last_error_ts is None or ts > last_error_ts):
                last_error_ts = ts
            if ts < cutoff:
                continue
            if level == "error":
                err_count += 1
            elif level == "warn":
                warn_count += 1
    return {
        "count_5m": err_count,
        "warn_count_5m": warn_count,
        "last_error_ts": last_error_ts,
        "window_seconds": int(window_seconds),
    }


def reset_recent_errors() -> None:
    """Clear the recent-errors ring buffer (test helper)."""
    with _recent_lock:
        _recent_errors.clear()


# ---------------------------------------------------------------------------
# Rate limiting — JTN-711: raised from capacity=10, refill=1/s.
#
# 60-token burst, refills at 10 tokens/s. A broken page can now emit ~60
# errors in a single burst without the browser reporter self-disabling, and
# each batched POST consumes only one token regardless of entry count.
# ---------------------------------------------------------------------------
_rate_limiter: TokenBucket = TokenBucket(capacity=60, refill_rate=10.0)

# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------
_MESSAGE_MAX = 2048  # bytes for message field
_ARGS_MAX = 4096  # bytes for args field
_BODY_MAX = 256 * 1024  # 256 KB total body — batch of 50 × ~4KB entries + slack
_BATCH_MAX = 50  # maximum entries per batch POST

# Accepted levels — info/debug rejected to avoid noise
_ACCEPTED_LEVELS = frozenset({"warn", "error"})


def _cap(value: object, max_len: int) -> str:
    """Coerce *value* to str and cap at *max_len* characters."""
    return str(value)[:max_len]


def _validate_and_normalize(entry: Any) -> tuple[dict[str, object] | None, str | None]:
    """Validate a single client-log entry dict.

    Returns ``(normalized_entry, None)`` on success or ``(None, error_message)``
    otherwise. Newline stripping happens downstream in ``_build_report``.
    """
    if not isinstance(entry, dict):
        return None, "entry must be a JSON object"

    level = entry.get("level", "")
    if level not in _ACCEPTED_LEVELS:
        logger.warning(
            "client log rejected: invalid level %s (accepted: %s)",
            sanitize_log_field(level),
            sorted(_ACCEPTED_LEVELS),
        )
        return None, f"Invalid level: must be one of {sorted(_ACCEPTED_LEVELS)}"
    return entry, None


def _strip_newlines(value: str) -> str:
    """Replace CR/LF with spaces to prevent log-injection (Sonar S5145)."""
    return value.replace("\r", " ").replace("\n", " ")


def _build_report(entry: dict[str, Any]) -> dict[str, object]:
    """Build the logged report dict from a validated entry.

    CR/LF is stripped from every field to prevent log injection
    (Sonar S5145). SecretRedactionFilter (JTN-364) handles secret stripping
    downstream in the logging layer.
    """
    report: dict[str, object] = {"level": entry["level"]}
    if "message" in entry:
        report["message"] = _strip_newlines(_cap(entry["message"], _MESSAGE_MAX))
    if "args" in entry:
        report["args"] = _strip_newlines(_cap(entry["args"], _ARGS_MAX))
    if "url" in entry:
        report["url"] = _strip_newlines(_cap(entry["url"], _MESSAGE_MAX))
    if "ts" in entry:
        report["ts"] = _strip_newlines(_cap(entry["ts"], 64))
    return report


def _emit(report: dict[str, object]) -> None:
    """Emit a single validated report to the logger and (optionally) capture."""
    logger.warning("client log [%s]: %s", report["level"], json.dumps(report))
    # Track every validated entry in the recent-errors ring buffer so the
    # diagnostics endpoint (JTN-709) can surface "something is broken" to the
    # in-app status badge.
    level = report.get("level")
    if isinstance(level, str):
        _record_recent(level)
    if _capture_enabled():
        with _captured_lock:
            _captured_reports.append(dict(report))


@client_log_bp.route("/api/client-log", methods=["POST"])
def receive_client_log() -> tuple[Response, int] | Response:
    """Accept a single entry OR an array of entries and log each as WARNING.

    * Single object payload: legacy shape, still supported (JTN-481).
    * Array payload: one POST carries up to ``_BATCH_MAX`` entries and
      consumes exactly one rate-limit token (JTN-711).

    Returns 204 on success. On batch requests where one or more entries fail
    validation, returns 400 with a JSON body listing per-entry errors so the
    client can fix the payload; valid entries in the same request are NOT
    emitted in that case (all-or-nothing semantics keep the contract simple).
    """
    # ---- Size + rate-limit (shared helper; parse_client_report isn't used
    # here because it hardcodes the dict requirement). ---------------------
    #
    # The helper already returns a server-controlled error tuple on failure,
    # but CodeQL can't prove the message is trusted through the boundary
    # (it treats everything derived from the request as tainted). We
    # reissue with a hardcoded message + the helper's status to break the
    # taint flow explicitly.
    raw_body, err = enforce_size_and_rate(_rate_limiter, _BODY_MAX)
    if err is not None:
        return reissue_json_error(err, "Request rejected")
    assert raw_body is not None

    try:
        data = json.loads(raw_body)
    except ValueError:
        return json_error("Request body must be valid JSON", status=400)

    # ---- Normalise single object vs batch array --------------------------
    if isinstance(data, list):
        entries = data
        if len(entries) == 0:
            return json_error("Batch must contain at least one entry", status=400)
        if len(entries) > _BATCH_MAX:
            return json_error(
                f"Batch too large: max {_BATCH_MAX} entries per POST", status=400
            )
    elif isinstance(data, dict):
        entries = [data]
    else:
        return json_error(
            "Request body must be a JSON object or array of objects", status=400
        )

    # ---- Validate every entry before emitting (all-or-nothing) -----------
    validated: list[dict[str, Any]] = []
    errors: list[dict[str, object]] = []
    for idx, entry in enumerate(entries):
        normalized, err = _validate_and_normalize(entry)
        if err is not None:
            errors.append({"index": idx, "error": err})
        else:
            assert normalized is not None
            validated.append(normalized)

    if errors:
        # Top-level error message is a fixed server-controlled string —
        # CodeQL flagged an earlier version because it tracks any value
        # derived from the request body as tainted, even when the code path
        # only ever picks from a fixed set of error strings. The full
        # per-entry list is still returned under ``details.entry_errors``
        # so batched senders can self-correct; each entry error message is
        # one of a small set of server-controlled literals built in
        # ``_validate_and_normalize``.
        return json_error(
            "One or more batch entries failed validation",
            status=400,
            details={"entry_errors": errors},
        )

    # ---- Emit every validated entry --------------------------------------
    for entry in validated:
        _emit(_build_report(entry))

    return Response(status=204)


@client_log_bp.route("/api/client-log", methods=["GET"])
def receive_client_log_get() -> tuple[Response, int]:
    """Explicitly reject GET to provide a clear error instead of 405 from Flask."""
    return json_error("Method not allowed", status=405)

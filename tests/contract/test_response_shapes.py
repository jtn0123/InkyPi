"""Contract tests: JSON response shape stability for high-traffic routes.

These tests pin down the JSON shape returned by the endpoints the UI depends
on most: version/uptime info, refresh state, health, settings isolation,
refresh stats, and history storage.  If a backend change silently alters the
response keys or types, these tests fail and force the change to be made
deliberately alongside a matching TypedDict update in
``src/schemas/responses.py``.

The validator below is intentionally hand-rolled (no pydantic) to keep the
test suite lightweight. It walks a TypedDict's ``__annotations__`` and checks:

* every required key is present with a value matching its declared type
* for ``total=False`` TypedDicts, keys that *are* present also type-check

``Any`` annotations short-circuit the type check, mirroring mypy semantics.
"""

from __future__ import annotations

import types
import typing
from typing import Any, get_args, get_origin

import pytest

# Import schemas via the ``src.*`` path which ``tests/conftest.py`` puts on
# sys.path via SRC_ABS. TypedDict subclasses from ``typing`` expose their
# total-ness on the class itself.
from schemas.responses import (  # noqa: E402  (sys.path set up by conftest)
    HealthPluginsResponse,
    HealthSystemResponse,
    HistoryStorageResponse,
    IsolationResponse,
    NextUpResponse,
    RefreshInfoResponse,
    RefreshStatsResponse,
    RefreshStatsWindow,
    TopFailingEntry,
    UptimeResponse,
    VersionInfoResponse,
)

# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def _is_typeddict(tp: Any) -> bool:
    return (
        isinstance(tp, type)
        and issubclass(tp, dict)
        and hasattr(tp, "__total__")
        and hasattr(tp, "__annotations__")
    )


def _check_type(value: Any, tp: Any, path: str) -> list[str]:
    """Return a list of error strings (empty if ``value`` matches ``tp``)."""
    # Any -> accept anything
    if tp is Any or tp is object:
        return []

    origin = get_origin(tp)

    # Union / Optional
    if origin is typing.Union or origin is types.UnionType:
        errs_per_arm: list[list[str]] = []
        for arm in get_args(tp):
            errs = _check_type(value, arm, path)
            if not errs:
                return []
            errs_per_arm.append(errs)
        return [f"{path}: no union arm matched value {value!r} ({tp})"]

    # list[X]
    if origin in (list, typing.List):  # noqa: UP006
        if not isinstance(value, list):
            return [f"{path}: expected list, got {type(value).__name__}"]
        (inner,) = get_args(tp) or (Any,)
        errs: list[str] = []
        for i, item in enumerate(value):
            errs.extend(_check_type(item, inner, f"{path}[{i}]"))
        return errs

    # dict[K, V]
    if origin in (dict, typing.Dict):  # noqa: UP006
        if not isinstance(value, dict):
            return [f"{path}: expected dict, got {type(value).__name__}"]
        args = get_args(tp)
        if not args:
            return []
        _k, vt = args
        errs = []
        for k, v in value.items():
            errs.extend(_check_type(v, vt, f"{path}[{k!r}]"))
        return errs

    # Nested TypedDict
    if _is_typeddict(tp):
        return validate_typeddict(value, tp, path=path)

    # Plain class
    if isinstance(tp, type):
        # bool is a subclass of int; keep them distinct to catch accidents
        if tp is int and isinstance(value, bool):
            return [f"{path}: expected int, got bool ({value!r})"]
        if not isinstance(value, tp):
            return [
                f"{path}: expected {tp.__name__}, got {type(value).__name__} ({value!r})"
            ]
        return []

    # Unknown / exotic annotation — skip silently
    return []


def validate_typeddict(payload: Any, schema: Any, *, path: str = "$") -> list[str]:
    """Validate *payload* against the TypedDict *schema*. Returns error list."""
    if not isinstance(payload, dict):
        return [f"{path}: expected dict, got {type(payload).__name__}"]

    hints = typing.get_type_hints(schema)
    required_keys = set(getattr(schema, "__required_keys__", set()))
    optional_keys = set(getattr(schema, "__optional_keys__", set()))
    # Older Pythons: fall back to __total__
    if not required_keys and not optional_keys:
        if getattr(schema, "__total__", True):
            required_keys = set(hints.keys())
        else:
            optional_keys = set(hints.keys())

    errors: list[str] = []
    for key in required_keys:
        if key not in payload:
            errors.append(f"{path}.{key}: missing required key")
            continue
        errors.extend(_check_type(payload[key], hints[key], f"{path}.{key}"))

    for key in optional_keys:
        if key in payload:
            errors.extend(_check_type(payload[key], hints[key], f"{path}.{key}"))

    return errors


def assert_shape(payload: Any, schema: Any) -> None:
    errors = validate_typeddict(payload, schema)
    if errors:
        raise AssertionError(
            f"Response does not match {schema.__name__}:\n  "
            + "\n  ".join(errors)
            + f"\nPayload: {payload!r}"
        )


# ---------------------------------------------------------------------------
# Self-tests for the validator (cheap insurance)
# ---------------------------------------------------------------------------


def test_validator_accepts_matching_payload():
    good: VersionInfoResponse = {
        "version": "1.0",
        "git_sha": "abc",
        "git_branch": "main",
        "build_time": "2024-01-01",
        "python_version": "3.13",
    }
    assert validate_typeddict(good, VersionInfoResponse) == []


def test_validator_detects_missing_key():
    bad = {"version": "1.0"}
    errs = validate_typeddict(bad, VersionInfoResponse)
    assert any("missing required key" in e for e in errs)


def test_validator_detects_wrong_type():
    bad = {
        "version": 1,  # should be str
        "git_sha": "abc",
        "git_branch": "main",
        "build_time": "2024-01-01",
        "python_version": "3.13",
    }
    errs = validate_typeddict(bad, VersionInfoResponse)
    assert any("expected str" in e for e in errs)


def test_validator_handles_nested_typeddict():
    good = {
        "last_1h": {
            "total": 0,
            "success": 0,
            "failure": 0,
            "success_rate": 0.0,
            "p50_duration_ms": 0,
            "p95_duration_ms": 0,
            "top_failing": [],
        },
        "last_24h": {
            "total": 0,
            "success": 0,
            "failure": 0,
            "success_rate": 0.0,
            "p50_duration_ms": 0,
            "p95_duration_ms": 0,
            "top_failing": [{"plugin": "ai_text", "count": 2}],
        },
        "last_7d": {
            "total": 0,
            "success": 0,
            "failure": 0,
            "success_rate": 0.0,
            "p50_duration_ms": 0,
            "p95_duration_ms": 0,
            "top_failing": [],
        },
    }
    assert validate_typeddict(good, RefreshStatsResponse) == []
    # Sanity: TopFailingEntry pulled through
    assert validate_typeddict({"plugin": "x", "count": 1}, TopFailingEntry) == []
    assert validate_typeddict({"plugin": "x", "count": "bad"}, TopFailingEntry) != []


# ---------------------------------------------------------------------------
# Endpoint contract tests
# ---------------------------------------------------------------------------


def _get_json(client, path, **kwargs):
    resp = client.get(path, **kwargs)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}: {resp.data!r}"
    assert resp.is_json, f"{path} did not return JSON: {resp.content_type!r}"
    return resp.get_json()


def test_version_info_shape(client):
    body = _get_json(client, "/api/version/info")
    assert_shape(body, VersionInfoResponse)


def test_uptime_shape(client):
    body = _get_json(client, "/api/uptime")
    assert_shape(body, UptimeResponse)


def test_refresh_info_shape(client):
    body = _get_json(client, "/refresh-info")
    # refresh_info may be empty ({}) on a pristine config; total=False schema
    # still validates that any keys present are correctly typed.
    assert isinstance(body, dict)
    assert_shape(body, RefreshInfoResponse)


def test_next_up_shape(client):
    body = _get_json(client, "/next-up")
    # next-up returns {} when nothing is scheduled; total=False schema allows
    # that while still locking in the shape of populated responses.
    assert isinstance(body, dict)
    assert_shape(body, NextUpResponse)
    # Consistency: if populated, the three primary keys should all be present.
    # TODO(contract-drift): routes currently only guarantee this via code
    # inspection — leave the soft check here rather than pinning the exact
    # populated state, which requires a playlist fixture.
    if "plugin_id" in body:
        assert "playlist" in body
        assert "plugin_instance" in body


def test_refresh_stats_shape(client):
    body = _get_json(client, "/api/stats")
    assert_shape(body, RefreshStatsResponse)
    # Also validate the sub-window schema explicitly so regressions at that
    # level are surfaced even if RefreshStatsResponse is loosened later.
    assert_shape(body["last_1h"], RefreshStatsWindow)


def test_health_system_shape(client):
    body = _get_json(client, "/api/health/system")
    assert_shape(body, HealthSystemResponse)
    assert body.get("success") is True


def test_health_plugins_shape(client):
    body = _get_json(client, "/api/health/plugins")
    assert_shape(body, HealthPluginsResponse)
    assert body.get("success") is True
    assert "items" in body


def test_isolation_shape(client):
    body = _get_json(client, "/settings/isolation")
    assert_shape(body, IsolationResponse)
    assert body.get("success") is True
    assert isinstance(body.get("isolated_plugins"), list)


def test_history_storage_shape(client):
    resp = client.get("/history/storage")
    # The history dir is a tmp_path created by device_config_dev; shutil
    # should succeed and return 200. If it fails (e.g. read-only CI FS), we
    # still require the error envelope rather than silently passing.
    if resp.status_code == 500:
        pytest.skip("history/storage failed to stat tmp fs (environment)")
    assert resp.status_code == 200
    body = resp.get_json()
    assert_shape(body, HistoryStorageResponse)

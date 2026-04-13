# pyright: reportMissingImports=false
"""Ensure weather plugin log calls redact potential API-key material (JTN-326).

CodeQL flagged weather_api.py:39/52/65 and weather_data.py:98 with
``py/clear-text-logging-sensitive-data`` because the enclosing functions
receive ``api_key``. These tests confirm the response body / tainted value
flowing into ``logger.*`` is wrapped with ``redact_secrets()`` so a leaked
key in an upstream error payload (or timezone field) never hits the handlers
in clear text.
"""

from __future__ import annotations

import logging

import pytest

from plugins.weather import weather_api, weather_data

# A 40-char hex string — matches the "raw 32+ hex" secret pattern in
# utils.logging_utils._SECRET_PATTERNS.
_FAKE_API_KEY = "a" * 40
_REDACTED = "***REDACTED***"


class _FailingResponse:
    status_code = 401

    def __init__(self, body: bytes) -> None:
        self.content = body

    def json(self) -> dict:  # pragma: no cover - not hit on failure path
        return {}


def _install_failing_session(monkeypatch, body: bytes) -> None:
    resp = _FailingResponse(body)
    session = type("S", (), {"get": staticmethod(lambda *a, **kw: resp)})()
    monkeypatch.setattr(weather_api, "get_http_session", lambda: session)


@pytest.mark.parametrize(
    "func, kwargs",
    [
        (
            weather_api.get_weather_data,
            {"api_key": _FAKE_API_KEY, "units": "metric", "lat": 0, "long": 0},
        ),
        (
            weather_api.get_air_quality,
            {"api_key": _FAKE_API_KEY, "lat": 0, "long": 0},
        ),
        (
            weather_api.get_location,
            {"api_key": _FAKE_API_KEY, "lat": 0, "long": 0},
        ),
    ],
)
def test_weather_api_redacts_response_body_on_error(func, kwargs, monkeypatch, caplog):
    """Response body containing an API-key-shaped token must be redacted."""
    leaky_body = (
        b'{"cod":401,"message":"Invalid api_key=' + _FAKE_API_KEY.encode() + b'"}'
    )
    _install_failing_session(monkeypatch, leaky_body)

    with caplog.at_level(logging.ERROR, logger="plugins.weather.weather_api"):
        with pytest.raises(RuntimeError):
            func(**kwargs)

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert _FAKE_API_KEY not in combined
    assert _REDACTED in combined


def test_parse_timezone_redacts_tainted_value(caplog):
    """Timezone field reaching the log site is passed through redact_secrets."""
    leaky = f"UTC api_key={_FAKE_API_KEY}"

    with caplog.at_level(logging.INFO, logger="plugins.weather.weather_data"):
        # ZoneInfo will reject the non-IANA string, so catch that — we only
        # care about the log call that runs before the ZoneInfo() lookup.
        with pytest.raises(Exception):
            weather_data.parse_timezone({"timezone": leaky})

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert _FAKE_API_KEY not in combined
    assert _REDACTED in combined

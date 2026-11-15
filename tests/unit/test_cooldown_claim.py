"""A cooldown is claimed before the action runs, not after it finishes.

"Display next" and reboot/shutdown used to test the cooldown, run the
action, then arm it. A refresh takes many seconds on a Pi Zero, so a
double click passed the test twice and started two refreshes.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

from utils.http_utils import json_success
from utils.rate_limiter import CooldownLimiter


class TestAcquire:
    def test_acquire_arms_the_cooldown(self) -> None:
        limiter = CooldownLimiter(10)
        assert limiter.acquire() == (True, 0.0)
        allowed, retry_after = limiter.acquire()
        assert allowed is False
        assert 0.0 < retry_after <= 10.0

    def test_only_one_of_many_simultaneous_callers_wins(self) -> None:
        limiter = CooldownLimiter(10)
        start = threading.Barrier(8)
        results: list[bool] = []
        results_lock = threading.Lock()

        def click() -> None:
            start.wait()
            allowed, _ = limiter.acquire()
            with results_lock:
                results.append(allowed)

        threads = [threading.Thread(target=click) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(results) == [False] * 7 + [True]

    def test_reset_after_a_failed_action_frees_the_slot(self) -> None:
        limiter = CooldownLimiter(10)
        assert limiter.acquire()[0] is True
        limiter.reset()
        assert limiter.acquire()[0] is True

    def test_record_restarts_the_cooldown_when_the_action_ends(self) -> None:
        limiter = CooldownLimiter(10)
        with patch("utils.rate_limiter.time.monotonic", return_value=100.0):
            assert limiter.acquire()[0] is True
        # The action took 30 s; the cooldown runs from its end.
        with patch("utils.rate_limiter.time.monotonic", return_value=130.0):
            limiter.record()
        with patch("utils.rate_limiter.time.monotonic", return_value=135.0):
            assert limiter.acquire() == (False, 5.0)

    def test_acquire_is_per_key(self) -> None:
        limiter = CooldownLimiter(10)
        assert limiter.acquire("a")[0] is True
        assert limiter.acquire("b")[0] is True
        assert limiter.acquire("a")[0] is False


def test_display_next_refuses_a_second_click_while_the_refresh_runs(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    import blueprints.main as main

    main._reset_display_next_cooldown()
    second_click: list[int] = []

    def slow_refresh() -> Any:
        second_click.append(flask_app.test_client().post("/display-next").status_code)
        return json_success(message="Display updated")

    monkeypatch.setattr(main, "_show_next_plugin", slow_refresh)

    assert client.post("/display-next").status_code == 200
    assert second_click == [429]
    # And the finished refresh starts the normal cooldown.
    assert client.post("/display-next").status_code == 429


def test_shutdown_refuses_a_second_request_while_the_first_runs(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import blueprints.settings as settings_mod

    settings_mod._shutdown_limiter.reset()
    second_request: list[int] = []

    def slow_shutdown(cmd: Any, check: bool = True) -> None:
        if not second_request:
            response = flask_app.test_client().post("/shutdown", json={})
            second_request.append(response.status_code)

    monkeypatch.setattr(subprocess, "run", slow_shutdown)

    assert client.post("/shutdown", json={}).status_code == 200
    assert second_request == [429]

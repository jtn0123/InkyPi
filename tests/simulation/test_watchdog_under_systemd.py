"""The watchdog, exercised over the real sd_notify wire protocol.

The unit tests in ``tests/unit/test_refresh_task_watchdog.py`` call the gating
predicate directly. These run the actual heartbeat thread with a real unix
datagram socket bound at ``$NOTIFY_SOCKET`` and a real ``WATCHDOG_USEC``, and
assert on the datagrams that genuinely arrive — the same bytes systemd would
receive on the device.

That covers the parts a predicate test cannot: that the interval is derived
correctly from the environment, that the thread actually sends anything, and —
the point of the change — that the pings *stop* when a refresh wedges, which is
what lets ``WatchdogSec`` expire and restart the unit.
"""

from __future__ import annotations

import threading
from pathlib import Path
from time import monotonic
from typing import Any
from unittest.mock import MagicMock

import pytest

from refresh_task import task as task_module
from refresh_task.task import RefreshTask
from tests.simulation.fake_systemd import (
    sd_notify,
    systemd_notify_environment,
    wait_until,
)

pytestmark = pytest.mark.simulation

#: What the device's ``WatchdogSec=120`` exports.
DEVICE_WATCHDOG_USEC = 120_000_000
#: Any value is fine for the socket tests — the ping cadence is pinned
#: separately (see PING_INTERVAL_S) because the real interval has a 1 s floor
#: that would make every cadence assertion take seconds.
WATCHDOG_USEC = DEVICE_WATCHDOG_USEC
#: Cadence used by the socket tests, patched over the derived interval.
PING_INTERVAL_S = 0.05
PING = "WATCHDOG=1"


@pytest.fixture
def task(monkeypatch: pytest.MonkeyPatch) -> Any:
    device_config = MagicMock()
    device_config.get_config.return_value = 3600  # a long, healthy cycle
    device_config.history_image_dir = "/tmp/history"
    instance = RefreshTask(device_config, MagicMock())
    # Stand in for cysystemd (Linux-only) with the same protocol in Python.
    monkeypatch.setattr(task_module, "_sd_notify", sd_notify)
    return instance


def _run_heartbeat(
    task: RefreshTask, monkeypatch: pytest.MonkeyPatch = None
) -> threading.Thread:
    if monkeypatch is not None:
        # Keep the socket and the gating real; only the cadence is accelerated,
        # because the derived interval floors at 1 s (see the interval tests).
        monkeypatch.setattr(
            RefreshTask,
            "_watchdog_interval_seconds",
            staticmethod(lambda: PING_INTERVAL_S),
        )
    task.running = True
    thread = threading.Thread(target=task._watchdog_heartbeat_loop, daemon=True)
    thread.start()
    return thread


def _stop_heartbeat(task: RefreshTask, thread: threading.Thread) -> None:
    task.running = False
    with task.condition:
        task.condition.notify_all()
    thread.join(timeout=2)


class TestIntervalComesFromTheEnvironment:
    def test_device_watchdog_sec_yields_half_interval(self, tmp_path: Path) -> None:
        """WatchdogSec=120 on the device means a ping every 60 s."""
        with systemd_notify_environment(tmp_path, DEVICE_WATCHDOG_USEC):
            assert RefreshTask._watchdog_interval_seconds() == pytest.approx(60.0)

    def test_interval_never_drops_below_one_second(self, tmp_path: Path) -> None:
        """A floor keeps a misconfigured tiny WatchdogSec from spinning the CPU.

        Worth pinning: it also means the cadence tests below cannot use the
        socket's WATCHDOG_USEC to go fast, which is why they patch the interval.
        """
        with systemd_notify_environment(tmp_path, 200_000):  # 0.2 s
            assert RefreshTask._watchdog_interval_seconds() == 1.0

    def test_absent_watchdog_usec_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WATCHDOG_USEC", raising=False)
        assert RefreshTask._watchdog_interval_seconds() == 30.0


class TestPingsReachTheSocket:
    def test_idle_loop_pings_repeatedly(
        self, tmp_path: Path, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An idle loop is healthy, however long the configured cycle is.

        The device's default cycle is an hour; the heartbeat must not be
        coupled to it (JTN-596).
        """
        with systemd_notify_environment(tmp_path, WATCHDOG_USEC) as sock:
            thread = _run_heartbeat(task, monkeypatch)
            try:
                assert wait_until(
                    lambda: sock.count(PING) >= 3
                ), f"expected repeated pings, saw {sock.count(PING)}"
            finally:
                _stop_heartbeat(task, thread)

    def test_pings_stop_once_a_refresh_wedges(
        self, tmp_path: Path, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point: a stuck refresh must let WatchdogSec expire.

        Before the gating change the heartbeat was a bare timer keyed on a
        boolean, so a refresh blocked forever in SPI or a subprocess kept
        systemd satisfied indefinitely and the watchdog could never fire for
        the one failure it exists to catch.
        """
        monkeypatch.setenv("INKYPI_REFRESH_STALL_TIMEOUT_SECONDS", "0.15")

        with systemd_notify_environment(tmp_path, WATCHDOG_USEC) as sock:
            thread = _run_heartbeat(task, monkeypatch)
            try:
                assert wait_until(lambda: sock.count(PING) >= 2), "no initial pings"

                # Simulate a refresh that began long ago and never returned.
                task._work_started_at = monotonic() - 60
                # Let any ping already in flight land, then take the baseline.
                wait_until(lambda: False, timeout=0.25)
                baseline = sock.count(PING)

                wait_until(lambda: False, timeout=0.4)
                assert (
                    sock.count(PING) == baseline
                ), "watchdog kept being fed while the refresh was wedged"
            finally:
                _stop_heartbeat(task, thread)

    def test_pings_resume_once_the_refresh_completes(
        self, tmp_path: Path, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A slow-but-recovering cycle must not leave the service dead."""
        monkeypatch.setenv("INKYPI_REFRESH_STALL_TIMEOUT_SECONDS", "0.15")

        with systemd_notify_environment(tmp_path, WATCHDOG_USEC) as sock:
            thread = _run_heartbeat(task, monkeypatch)
            try:
                task._work_started_at = monotonic() - 60
                wait_until(lambda: False, timeout=0.3)
                stalled = sock.count(PING)

                # Refresh finally finishes; the loop returns to idle.
                task._work_started_at = None
                assert wait_until(
                    lambda: sock.count(PING) > stalled, timeout=2.0
                ), "watchdog never resumed after the refresh completed"
            finally:
                _stop_heartbeat(task, thread)

    def test_a_long_but_healthy_refresh_keeps_pinging(
        self, tmp_path, task, monkeypatch
    ) -> None:
        """AI image generation legitimately takes minutes; that is not a hang."""
        monkeypatch.setenv("INKYPI_REFRESH_STALL_TIMEOUT_SECONDS", "600")

        with systemd_notify_environment(tmp_path, WATCHDOG_USEC) as sock:
            thread = _run_heartbeat(task, monkeypatch)
            try:
                task._work_started_at = monotonic() - 120  # two minutes in
                before = sock.count(PING)
                assert wait_until(
                    lambda: sock.count(PING) >= before + 3
                ), "a slow but healthy refresh must keep feeding the watchdog"
            finally:
                _stop_heartbeat(task, thread)


class TestThreadWiring:
    def test_start_launches_the_heartbeat_when_systemd_is_present(
        self, tmp_path, task, monkeypatch
    ) -> None:
        """Under Type=notify the thread must actually be created."""
        monkeypatch.setattr(task, "_run", lambda: None)
        with systemd_notify_environment(tmp_path, WATCHDOG_USEC):
            task.start()
            try:
                assert task.watchdog_thread is not None
                assert task.watchdog_thread.is_alive()
            finally:
                task.stop()

    def test_no_heartbeat_thread_without_systemd(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Off-device there is no socket to feed, so no thread should spawn."""
        monkeypatch.setattr(task_module, "_sd_notify", None)
        device_config = MagicMock()
        device_config.get_config.return_value = 3600
        device_config.history_image_dir = "/tmp/history"
        instance = RefreshTask(device_config, MagicMock())
        monkeypatch.setattr(instance, "_run", lambda: None)
        instance.start()
        try:
            assert instance.watchdog_thread is None
        finally:
            instance.stop()

# pyright: reportMissingImports=false
"""Tests for the cross-process headless-Chromium slot (utils.chromium_limiter)."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from utils.chromium_limiter import chromium_slot, lock_file_path, slot_wait_limit
from utils.plugin_errors import ScreenshotBackendError

_SRC_DIR = str(Path(__file__).resolve().parents[2] / "src")


@pytest.fixture(autouse=True)
def isolated_lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("INKYPI_CHROMIUM_LOCK_DIR", str(tmp_path))
    return tmp_path


def _slot_is_free() -> bool:
    """Probe the slot from an independent descriptor without waiting."""
    fd = os.open(lock_file_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


def _spawn_holder(lock_dir: Path, body: str) -> subprocess.Popen[bytes]:
    """Start a separate Python process that grabs the slot and runs *body*."""
    script = textwrap.dedent("""
        import os, sys, time
        from utils.chromium_limiter import chromium_slot
        with chromium_slot("test holder"):
            sys.stdout.write("held\\n")
            sys.stdout.flush()
        """) + textwrap.indent(textwrap.dedent(body), "    ")
    env = {
        **os.environ,
        "PYTHONPATH": _SRC_DIR,
        "INKYPI_CHROMIUM_LOCK_DIR": str(lock_dir),
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, env=env
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == b"held"
    return proc


def test_lock_file_lives_in_configured_dir(isolated_lock_dir: Path) -> None:
    assert lock_file_path() == str(isolated_lock_dir / "inkypi-chromium.lock")


def test_concurrent_thread_launches_are_serialized() -> None:
    intervals: list[tuple[float, float]] = []
    record = threading.Lock()
    start = threading.Barrier(2)

    def fake_launch() -> None:
        start.wait()
        with chromium_slot("fake launcher", timeout_s=5):
            began = time.monotonic()
            time.sleep(0.3)
            ended = time.monotonic()
        with record:
            intervals.append((began, ended))

    threads = [threading.Thread(target=fake_launch) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(intervals) == 2
    first, second = sorted(intervals)
    assert second[0] >= first[1], f"launches overlapped: {intervals}"


def test_slot_is_held_across_processes(isolated_lock_dir: Path) -> None:
    proc = _spawn_holder(isolated_lock_dir, "time.sleep(0.6)")
    try:
        started = time.monotonic()
        with chromium_slot("main process", timeout_s=10):
            waited = time.monotonic() - started
            # The holder process must have finished its critical section.
            assert proc.wait(timeout=5) == 0
    finally:
        proc.kill()
        proc.wait()
    assert waited >= 0.3


def test_busy_slot_times_out_with_backend_error(isolated_lock_dir: Path) -> None:
    proc = _spawn_holder(isolated_lock_dir, "time.sleep(30)")
    try:
        started = time.monotonic()
        slot = chromium_slot("starved", timeout_s=0.3)
        with pytest.raises(ScreenshotBackendError, match="Renderer busy"), slot:
            pytest.fail("slot should not have been granted")
        assert time.monotonic() - started < 5
    finally:
        proc.kill()
        proc.wait()


def test_slot_released_when_holder_process_is_killed(isolated_lock_dir: Path) -> None:
    proc = _spawn_holder(isolated_lock_dir, "time.sleep(30)")
    assert not _slot_is_free()
    proc.kill()
    proc.wait()
    with chromium_slot("after crash", timeout_s=2):
        pass


def test_slot_released_when_launch_raises() -> None:
    slot = chromium_slot("failing launcher", timeout_s=1)
    with pytest.raises(RuntimeError, match="boom"), slot:
        assert not _slot_is_free()
        raise RuntimeError("boom")
    assert _slot_is_free()
    with chromium_slot("next launcher", timeout_s=0):
        pass


def test_slot_is_reentrant_within_a_thread() -> None:
    with chromium_slot("outer", timeout_s=1):
        with chromium_slot("inner", timeout_s=0):
            assert not _slot_is_free()
        assert not _slot_is_free()
    assert _slot_is_free()


def test_slot_wait_limit_caps_default_wait(
    isolated_lock_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_CHROMIUM_LOCK_TIMEOUT_S", "30")
    proc = _spawn_holder(isolated_lock_dir, "time.sleep(30)")
    try:
        started = time.monotonic()
        with slot_wait_limit(0.2), pytest.raises(ScreenshotBackendError):
            with chromium_slot("request thread"):
                pass
        assert time.monotonic() - started < 5
    finally:
        proc.kill()
        proc.wait()


def test_unopenable_lock_file_fails_open(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _deny(*_args: Any, **_kwargs: Any) -> int:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "open", _deny)
    ran = False
    with chromium_slot("no lock file"):
        ran = True
    assert ran
    assert "without a concurrency cap" in caplog.text


def test_browser_subprocess_runs_inside_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils import image_utils

    observed: dict[str, bool] = {}

    def fake_run(command: Any, **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed["slot_free_during_launch"] = _slot_is_free()
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result, transient = image_utils._run_browser_subprocess(["chromium"], 1.0, 1)

    assert result is not None
    assert not transient
    assert observed == {"slot_free_during_launch": False}
    assert _slot_is_free()


def test_browser_subprocess_busy_slot_raises_backend_error(
    isolated_lock_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from utils import image_utils

    monkeypatch.setenv("INKYPI_CHROMIUM_LOCK_TIMEOUT_S", "0.2")
    launched: list[object] = []
    monkeypatch.setattr(
        image_utils, "_find_browser_command", lambda *a, **k: ["chromium"]
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: launched.append(a))
    proc = _spawn_holder(isolated_lock_dir, "time.sleep(30)")
    try:
        with pytest.raises(ScreenshotBackendError):
            # ``take_screenshot`` itself is stubbed by the suite-wide
            # ``mock_screenshot`` fixture, so drive the per-attempt helper.
            image_utils._take_screenshot_once("file:///tmp/x.html", (10, 10), None, 1)
    finally:
        proc.kill()
        proc.wait()
    assert launched == []

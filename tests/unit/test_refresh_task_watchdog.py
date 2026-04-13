# pyright: reportMissingImports=false
"""Unit tests for the watchdog heartbeat thread added in JTN-596.

Verifies that RefreshTask feeds the systemd watchdog independently of the
refresh cycle duration, so a long plugin_cycle_interval_seconds cannot starve
the watchdog and cause systemd to SIGABRT the service.
"""

import enum
import importlib
import importlib.util
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# Helpers for loading task.py with a mocked cysystemd
# ---------------------------------------------------------------------------


class FakeNotification(enum.Enum):
    READY = "READY=1"
    WATCHDOG = "WATCHDOG=1"
    STOPPING = "STOPPING=1"


def _load_task_module(*, with_sd_notify: bool = True, module_alias: str = ""):
    """Load src/refresh_task/task.py with cysystemd stubbed.

    Parameters
    ----------
    with_sd_notify:
        When True the module-level ``_sd_notify`` callable is set (simulates
        a Pi with cysystemd installed).  When False it is ``None`` (simulates
        running outside systemd).
    module_alias:
        Unique name to register in sys.modules so repeated calls don't collide.
    """
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))

    name = module_alias or f"task_jtn596_test_{with_sd_notify}"
    if name in sys.modules:
        del sys.modules[name]

    stub_mods: dict[str, types.ModuleType | None] = {
        "waveshare_epd": types.ModuleType("waveshare_epd"),
        "gpiozero": types.ModuleType("gpiozero"),
        "PIL": types.ModuleType("PIL"),
        "PIL.Image": types.ModuleType("PIL.Image"),
        "PIL.ImageDraw": types.ModuleType("PIL.ImageDraw"),
        "PIL.ImageFont": types.ModuleType("PIL.ImageFont"),
    }

    if with_sd_notify:
        fake_notify = MagicMock()
        fake_daemon = types.ModuleType("cysystemd.daemon")
        fake_daemon.notify = fake_notify  # type: ignore[attr-defined]
        fake_daemon.Notification = FakeNotification  # type: ignore[attr-defined]
        fake_cysystemd = types.ModuleType("cysystemd")
        fake_cysystemd.daemon = fake_daemon  # type: ignore[attr-defined]
        stub_mods["cysystemd"] = fake_cysystemd
        stub_mods["cysystemd.daemon"] = fake_daemon
    else:
        # None entries cause ImportError on 'from cysystemd…'
        stub_mods["cysystemd"] = None  # type: ignore[assignment]
        stub_mods["cysystemd.daemon"] = None  # type: ignore[assignment]
        fake_notify = None

    spec = importlib.util.spec_from_file_location(
        name, SRC_DIR / "refresh_task" / "task.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]

    with patch.dict(sys.modules, stub_mods):
        spec.loader.exec_module(module)  # type: ignore[union-attr]

    return module, fake_notify


def _make_refresh_task(module, *, with_sd_notify: bool = True):
    """Instantiate a RefreshTask with minimal mocked dependencies."""
    device_config = MagicMock()
    device_config.get_config.return_value = 3600  # default 1-hour cycle
    device_config.get_playlist_manager.return_value = MagicMock()
    device_config.get_refresh_info.return_value = None
    device_config.history_image_dir = "/tmp/history"

    display_manager = MagicMock()

    return module.RefreshTask(device_config, display_manager)


# ---------------------------------------------------------------------------
# Test 1 — _watchdog_interval_seconds reads WATCHDOG_USEC correctly
# ---------------------------------------------------------------------------


class TestWatchdogIntervalSeconds:
    """_watchdog_interval_seconds() must compute half of WATCHDOG_USEC in seconds."""

    def setup_method(self):
        self.module, _ = _load_task_module(
            with_sd_notify=True, module_alias="task_interval_test"
        )

    def test_120s_watchdog_usec(self, monkeypatch):
        monkeypatch.setenv("WATCHDOG_USEC", "120000000")
        assert self.module.RefreshTask._watchdog_interval_seconds() == 60.0

    def test_60s_watchdog_usec(self, monkeypatch):
        monkeypatch.setenv("WATCHDOG_USEC", "60000000")
        assert self.module.RefreshTask._watchdog_interval_seconds() == 30.0

    def test_empty_string_defaults_to_30(self, monkeypatch):
        monkeypatch.setenv("WATCHDOG_USEC", "")
        assert self.module.RefreshTask._watchdog_interval_seconds() == 30.0

    def test_unset_defaults_to_30(self, monkeypatch):
        monkeypatch.delenv("WATCHDOG_USEC", raising=False)
        assert self.module.RefreshTask._watchdog_interval_seconds() == 30.0

    def test_invalid_string_defaults_to_30(self, monkeypatch):
        monkeypatch.setenv("WATCHDOG_USEC", "not_a_number")
        assert self.module.RefreshTask._watchdog_interval_seconds() == 30.0

    def test_zero_defaults_to_30(self, monkeypatch):
        monkeypatch.setenv("WATCHDOG_USEC", "0")
        assert self.module.RefreshTask._watchdog_interval_seconds() == 30.0

    def test_minimum_is_1_second(self, monkeypatch):
        # Very small WATCHDOG_USEC (e.g. 100µs) should still yield at least 1s
        monkeypatch.setenv("WATCHDOG_USEC", "100")
        assert self.module.RefreshTask._watchdog_interval_seconds() == 1.0


# ---------------------------------------------------------------------------
# Test 2 — watchdog_thread is started when sd_notify is available
# ---------------------------------------------------------------------------


class TestWatchdogThreadStartsWithRefreshTask:
    """start() must spawn a WatchdogHeartbeat thread when cysystemd is available."""

    def test_watchdog_thread_starts(self, monkeypatch):
        module, _ = _load_task_module(
            with_sd_notify=True, module_alias="task_thread_start_test"
        )
        task = _make_refresh_task(module, with_sd_notify=True)

        # Use a blocking heartbeat loop so the thread stays alive long enough to assert.
        started = threading.Event()

        def blocking_heartbeat_loop():
            started.set()
            # Block until task.running is False
            with task.condition:
                task.condition.wait_for(lambda: not task.running, timeout=5)

        monkeypatch.setattr(task, "_watchdog_heartbeat_loop", blocking_heartbeat_loop)

        task.thread = None
        with patch.object(task, "_run"):
            task.start()

        # Wait until the heartbeat thread has actually entered its body
        started.wait(timeout=2)

        assert task.watchdog_thread is not None
        assert task.watchdog_thread.is_alive()

        # Clean up
        task.running = False
        with task.condition:
            task.condition.notify_all()
        task.watchdog_thread.join(timeout=1)


# ---------------------------------------------------------------------------
# Test 3 — watchdog_heartbeat_loop pings repeatedly
# ---------------------------------------------------------------------------


class TestWatchdogHeartbeatPingsRepeatedly:
    """The heartbeat loop must ping _notify_watchdog at the configured cadence."""

    def test_pings_at_least_4_times_in_300ms(self, monkeypatch):
        module, _ = _load_task_module(
            with_sd_notify=True, module_alias="task_ping_repeat_test"
        )
        task = _make_refresh_task(module, with_sd_notify=True)

        ping_count = 0

        def fake_notify_watchdog():
            nonlocal ping_count
            ping_count += 1

        # Use 50ms interval → expect ≥4 pings in 300ms
        monkeypatch.setattr(
            module.RefreshTask,
            "_watchdog_interval_seconds",
            staticmethod(lambda: 0.05),
        )
        monkeypatch.setattr(task, "_notify_watchdog", fake_notify_watchdog)

        task.running = True
        hb_thread = threading.Thread(target=task._watchdog_heartbeat_loop, daemon=True)
        hb_thread.start()

        time.sleep(0.35)

        task.running = False
        with task.condition:
            task.condition.notify_all()
        hb_thread.join(timeout=1)

        assert ping_count >= 4, (
            f"Expected at least 4 watchdog pings in 300ms with 50ms interval, "
            f"got {ping_count}"
        )


# ---------------------------------------------------------------------------
# Test 4 — no watchdog thread when sd_notify is unavailable
# ---------------------------------------------------------------------------


class TestWatchdogNoThreadWhenSdNotifyUnavailable:
    """start() must NOT spawn a WatchdogHeartbeat thread when cysystemd is absent."""

    def test_watchdog_thread_is_none_without_sd_notify(self):
        module, _ = _load_task_module(
            with_sd_notify=False, module_alias="task_no_thread_test"
        )
        task = _make_refresh_task(module, with_sd_notify=False)

        assert module._sd_notify is None, "_sd_notify should be None in this module"

        with (
            patch.object(task, "_run"),
            patch.object(task, "_watchdog_heartbeat_loop"),
        ):
            task.start()

        assert task.watchdog_thread is None


# ---------------------------------------------------------------------------
# Test 5 — heartbeat loop stops when running flag is cleared
# ---------------------------------------------------------------------------


class TestWatchdogHeartbeatStopsWithRunningFlag:
    """_watchdog_heartbeat_loop must exit promptly when self.running is set False."""

    def test_thread_exits_within_1_second(self, monkeypatch):
        module, _ = _load_task_module(
            with_sd_notify=True, module_alias="task_stops_test"
        )
        task = _make_refresh_task(module, with_sd_notify=True)

        # Use a long interval so we know the condition.notify_all() wakes the thread
        monkeypatch.setattr(
            module.RefreshTask,
            "_watchdog_interval_seconds",
            staticmethod(lambda: 60.0),
        )
        monkeypatch.setattr(task, "_notify_watchdog", lambda: None)

        task.running = True
        hb_thread = threading.Thread(target=task._watchdog_heartbeat_loop, daemon=True)
        hb_thread.start()

        # Give it a moment to enter the condition.wait()
        time.sleep(0.05)

        task.running = False
        with task.condition:
            task.condition.notify_all()

        hb_thread.join(timeout=1)
        assert not hb_thread.is_alive(), (
            "WatchdogHeartbeat thread did not stop within 1 second after "
            "running=False + condition.notify_all()"
        )

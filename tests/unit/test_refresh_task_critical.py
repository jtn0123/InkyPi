# pyright: reportMissingImports=false
"""Tests for critical untested paths in refresh_task.py (JTN-71).

Covers:
- _remote_exception()
- _get_mp_context()
- _execute_refresh_attempt_worker()
- RefreshTask.stop()
- _execute_with_policy() error/timeout paths
"""

import os
import queue
import threading
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from PIL import Image

from refresh_task import (
    ManualUpdateRequest,
    RefreshTask,
    _get_mp_context,
    _remote_exception,
)

# ---------------------------------------------------------------------------
# _remote_exception
# ---------------------------------------------------------------------------


class _SpawnableAction:
    """Module-scope so `multiprocessing.spawn` can pickle instances
    across the subprocess boundary (local classes are unpicklable).
    Used only by `test_worker_reloads_plugin_registry_in_real_spawned_child`.
    """

    def execute(self, plugin, cfg, dt):
        return Image.new("RGB", (10, 10), "green")


class _LargeImageAction:
    """Module-scope action that returns an image whose PNG encoding is
    guaranteed to exceed 64 KB (the Linux default pipe buffer).  Used by
    the pipe-buffer deadlock regression test.

    Random pixels ensure the PNG barely compresses — 800x480 RGB random
    data yields a PNG of ~1.1 MB, well past the 64 KB threshold at which
    the old ``result_queue.put(image_bytes)`` path deadlocked.
    """

    def execute(self, plugin, cfg, dt):
        data = os.urandom(800 * 480 * 3)
        return Image.frombytes("RGB", (800, 480), data)


class TestRemoteException:
    def test_known_types(self):
        for name, cls in [
            ("RuntimeError", RuntimeError),
            ("ValueError", ValueError),
            ("TimeoutError", TimeoutError),
            ("TypeError", TypeError),
            ("FileNotFoundError", FileNotFoundError),
        ]:
            exc = _remote_exception(name, "msg")
            assert isinstance(exc, cls)
            assert str(exc) == "msg"

    def test_key_error(self):
        exc = _remote_exception("KeyError", "missing_key")
        assert isinstance(exc, KeyError)
        assert "missing_key" in str(exc)

    def test_unknown_type_defaults_to_runtime_error(self):
        exc = _remote_exception("SomeWeirdError", "oops")
        assert isinstance(exc, RuntimeError)
        assert "oops" in str(exc)


# ---------------------------------------------------------------------------
# _get_mp_context
# ---------------------------------------------------------------------------


class TestGetMpContext:
    def test_returns_context(self):
        ctx = _get_mp_context()
        assert ctx is not None
        assert hasattr(ctx, "Process")
        assert hasattr(ctx, "Queue")


# ---------------------------------------------------------------------------
# _execute_refresh_attempt_worker — success path
# ---------------------------------------------------------------------------


class TestExecuteRefreshAttemptWorker:
    def test_success_puts_ok_payload(self, device_config_dev):
        from refresh_task import _execute_refresh_attempt_worker

        result_queue = queue.Queue()

        class FakePlugin:
            def generate_image(self, settings, cfg):
                return Image.new("RGB", (10, 10), "red")

            def get_latest_metadata(self):
                return {"key": "val"}

        class FakeAction:
            def execute(self, plugin, cfg, dt):
                return plugin.generate_image(None, cfg)

        # Mock get_plugin_instance and _restore_child_config
        with (
            patch("refresh_task.worker.get_plugin_instance", return_value=FakePlugin()),
            patch(
                "refresh_task.worker._restore_child_config",
                return_value=device_config_dev,
            ),
        ):
            _execute_refresh_attempt_worker(
                result_queue,
                {"id": "test"},
                FakeAction(),
                device_config_dev,
                datetime.now(UTC),
            )

        payload = result_queue.get_nowait()
        assert payload["ok"] is True
        assert "image_path" in payload
        # Verify it's a valid PNG at the returned path
        img = Image.open(payload["image_path"])
        assert img.size == (10, 10)
        img.close()
        os.unlink(payload["image_path"])

    def test_none_image_puts_error(self, device_config_dev):
        from refresh_task import _execute_refresh_attempt_worker

        result_queue = queue.Queue()

        class NullPlugin:
            def generate_image(self, settings, cfg):
                return None

        class FakeAction:
            def execute(self, plugin, cfg, dt):
                return None

        with (
            patch("refresh_task.worker.get_plugin_instance", return_value=NullPlugin()),
            patch(
                "refresh_task.worker._restore_child_config",
                return_value=device_config_dev,
            ),
        ):
            _execute_refresh_attempt_worker(
                result_queue,
                {"id": "test"},
                FakeAction(),
                device_config_dev,
                datetime.now(UTC),
            )

        payload = result_queue.get_nowait()
        assert payload["ok"] is False
        assert payload["error_type"] == "RuntimeError"
        assert "None" in payload["error_message"]

    def test_exception_puts_error_payload(self, device_config_dev):
        from refresh_task import _execute_refresh_attempt_worker

        result_queue = queue.Queue()

        class BrokenAction:
            def execute(self, plugin, cfg, dt):
                raise ValueError("bad config")

        with (
            patch("refresh_task.worker.get_plugin_instance", return_value=MagicMock()),
            patch(
                "refresh_task.worker._restore_child_config",
                return_value=device_config_dev,
            ),
        ):
            _execute_refresh_attempt_worker(
                result_queue,
                {"id": "test"},
                BrokenAction(),
                device_config_dev,
                datetime.now(UTC),
            )

        payload = result_queue.get_nowait()
        assert payload["ok"] is False
        assert payload["error_type"] == "ValueError"
        assert "bad config" in payload["error_message"]
        assert "traceback" in payload
        # Pin the error path: failures must NOT carry an image_path.  The
        # tempfile is only created in the success branch (after generate_image
        # succeeds).  If a future refactor moves tempfile creation earlier
        # — e.g. up next to the try block — the error branch could leak a
        # 0-byte file the parent never reads or unlinks.  Asserting absence
        # here keeps the leak-free contract pinned.
        assert "image_path" not in payload, (
            "error payloads must not include 'image_path' — that would leak "
            "a tempfile the parent's _handle_process_result never reads"
        )

    def test_worker_reloads_plugin_registry_in_child(self, device_config_dev):
        """JTN-783: spawned subprocess starts with empty plugin registry.

        Simulates the real bug: when multiprocessing spawn/forkserver starts a
        child process, the module-level `PLUGIN_CLASSES` / `_PLUGIN_CONFIGS`
        dicts in `plugins.plugin_registry` are empty. The worker must call
        `load_plugins(child_config.get_plugins())` so `get_plugin_instance`
        can resolve the plugin_id, otherwise every manual `/update_now` in
        the default `process` isolation mode raises
        `ValueError: Plugin 'clock' is not registered.`.

        This test fails on main (before the fix) because the worker calls
        `get_plugin_instance` against an empty registry.
        """
        # Simulate a freshly-spawned child: wipe the module-level registries
        # the same way `spawn` would (child gets a fresh interpreter).
        from plugins import plugin_registry
        from refresh_task import _execute_refresh_attempt_worker
        from refresh_task.context import RefreshContext

        saved_classes = dict(plugin_registry.PLUGIN_CLASSES)
        saved_configs = dict(plugin_registry._PLUGIN_CONFIGS)
        plugin_registry.PLUGIN_CLASSES.clear()
        plugin_registry._PLUGIN_CONFIGS.clear()

        # Use a real plugin_id the bundled Config will discover from the
        # plugins/ directory tree. `clock` is a stable, always-present plugin.
        plugin_config = {"id": "clock", "class": "Clock"}
        refresh_context = RefreshContext.from_config(device_config_dev)

        class FakeAction:
            def execute(self, plugin, cfg, dt):
                return Image.new("RGB", (10, 10), "blue")

        result_queue = queue.Queue()
        try:
            _execute_refresh_attempt_worker(
                result_queue,
                plugin_config,
                FakeAction(),
                refresh_context,
                datetime.now(UTC),
            )
            payload = result_queue.get_nowait()
            # With the fix: worker calls load_plugins(child_config.get_plugins())
            # before get_plugin_instance, so the clock plugin resolves and the
            # fake action returns a valid image.
            assert (
                payload["ok"] is True
            ), f"Expected ok=True after registry reload; got: {payload}"
            assert "image_path" in payload
            os.unlink(payload["image_path"])
            # Registry should now contain clock (populated by load_plugins).
            assert "clock" in plugin_registry.get_registered_plugin_ids()
        finally:
            # Restore whatever the suite had before this test ran.
            plugin_registry.PLUGIN_CLASSES.clear()
            plugin_registry._PLUGIN_CONFIGS.clear()
            plugin_registry.PLUGIN_CLASSES.update(saved_classes)
            plugin_registry._PLUGIN_CONFIGS.update(saved_configs)

    def test_worker_reloads_plugin_registry_in_real_spawned_child(
        self, device_config_dev
    ):
        """JTN-783: end-to-end variant that spawns a real subprocess.

        The inline variant above simulates a cold registry by clearing the
        parent's module-level dicts, but it still executes in the parent's
        address space. This variant drives the full multiprocessing start
        method (``spawn`` on macOS + the production systemd service), which
        is the path that actually shipped the JTN-783 bug to users. If the
        worker ever regresses back to calling ``get_plugin_instance`` on
        the spawned child's empty registry, this test fails with the exact
        production error instead of the simulation.
        """
        from refresh_task import _execute_refresh_attempt_worker
        from refresh_task.context import RefreshContext

        plugin_config = {"id": "clock", "class": "Clock"}
        refresh_context = RefreshContext.from_config(device_config_dev)

        ctx = _get_mp_context()
        result_queue = ctx.Queue(maxsize=1)
        proc = ctx.Process(
            target=_execute_refresh_attempt_worker,
            args=(
                result_queue,
                plugin_config,
                _SpawnableAction(),
                refresh_context,
                datetime.now(UTC),
            ),
            daemon=True,
        )
        proc.start()
        # 30s is generous for spawn + plugin-info.json discovery + one fake
        # action call; well below the per-attempt 60s default in production.
        proc.join(timeout=30)
        try:
            assert not proc.is_alive(), (
                "spawned worker did not exit within 30s — "
                "probably stuck before result_queue.put()"
            )
            payload = result_queue.get(timeout=5)
        finally:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)

        assert payload["ok"] is True, (
            f"Real spawned child failed to resolve plugin from cold "
            f"registry — JTN-783 regression. payload={payload}"
        )
        assert "image_path" in payload
        os.unlink(payload["image_path"])


# ---------------------------------------------------------------------------
# Pipe-buffer deadlock regression
# ---------------------------------------------------------------------------


class TestSubprocessPipeBufferDeadlockRegression:
    """Guards the Linux pipe-buffer deadlock that made every /update_now
    time out on real hardware.

    The prior shape of the worker payload was
    ``{"image_bytes": <PNG bytes>, ...}``.  ``multiprocessing.Queue.put``
    hands the pickled payload to a background feeder thread which writes
    it to a pipe with a 65,536-byte buffer.  For any payload over 64 KB
    (i.e. every real-world plugin PNG), the feeder blocks on the second
    pipe write until the reader drains the pipe — but the parent is
    blocked inside ``proc.join()`` waiting for the child to exit, and
    the child cannot exit until the feeder completes.  Result: every
    render hit the 60s manual-update timeout.

    The fix (this PR) is to write the PNG to a tempfile in the child and
    put only the path (< 1 KB) on the queue.  If anyone reverts that and
    reintroduces a large-payload ``put``, this test hangs until its own
    short timeout fires — and fails loudly instead of silently.
    """

    def test_large_image_round_trips_under_deadlock_threshold(self, device_config_dev):
        """Real spawned subprocess + 800x480 random-pixel image.

        Must complete well under 10 s.  With the pipe-buffer deadlock
        regressed, this hangs for the full timeout and then fails on
        ``not proc.is_alive()``.
        """
        from refresh_task import _execute_refresh_attempt_worker
        from refresh_task.context import RefreshContext

        plugin_config = {"id": "clock", "class": "Clock"}
        refresh_context = RefreshContext.from_config(device_config_dev)

        ctx = _get_mp_context()
        result_queue = ctx.Queue(maxsize=1)
        proc = ctx.Process(
            target=_execute_refresh_attempt_worker,
            args=(
                result_queue,
                plugin_config,
                _LargeImageAction(),
                refresh_context,
                datetime.now(UTC),
            ),
            daemon=True,
        )
        proc.start()
        # 10 s is generous for spawn + plugin-info discovery + one action call
        # + tempfile write on the tightest CI hardware.  The pre-fix deadlock
        # path never exits, so any wait long enough to ~exclude~ the deadlock
        # is fine; 10 s gives a clean signal without slowing the suite.
        proc.join(timeout=10)
        try:
            assert not proc.is_alive(), (
                "spawned worker did not exit within 10s — pipe-buffer "
                "deadlock regressed; the child is stuck in queue.feeder "
                "waiting for the parent to drain a >64 KB payload, but "
                "the parent is waiting on proc.join()."
            )
            payload = result_queue.get(timeout=5)
        finally:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)

        assert payload["ok"] is True, f"worker reported failure: {payload}"
        # Payload must carry a path, not bytes — the whole point of the fix.
        assert "image_path" in payload, (
            "worker payload must carry 'image_path' (tempfile), not "
            "'image_bytes' — raw bytes through a multiprocessing.Queue "
            "deadlock on payloads > 64 KB."
        )
        assert "image_bytes" not in payload, (
            "worker payload must NOT carry 'image_bytes' — that reintroduces "
            "the pipe-buffer deadlock for any real-size PNG."
        )

        # Verify the tempfile exists, is a valid large PNG, then clean up.
        png_path = payload["image_path"]
        assert os.path.exists(png_path), f"tempfile missing: {png_path}"
        size_bytes = os.path.getsize(png_path)
        assert size_bytes > 64 * 1024, (
            f"test fixture is too small ({size_bytes} bytes) to exercise "
            "the >64 KB deadlock threshold; expected >65,536 bytes"
        )
        img = Image.open(png_path)
        assert img.size == (800, 480)
        img.close()
        os.unlink(png_path)


# ---------------------------------------------------------------------------
# Worker session-leader cleanup (JTN-S2)
# ---------------------------------------------------------------------------


class TestWorkerSessionLeaderCleanup:
    """JTN-S2: the worker becomes a session leader on startup so the
    parent's ``_cleanup_subprocess`` can ``killpg(SIGKILL)`` the entire
    chromium tree (worker + chromium + zygote + renderers + utility) in
    one syscall.  Without this, chromium descendants get reparented to
    PID 1 and leak.
    """

    def test_worker_calls_setsid_to_become_session_leader(self, monkeypatch):
        """The worker must call ``os.setsid()`` before doing any plugin
        work so chromium spawned later inherits the worker's pgid.
        """
        import queue as _queue

        from refresh_task import _execute_refresh_attempt_worker

        called: list[bool] = []

        def fake_setsid():
            called.append(True)

        # Patch the worker module's ``os`` reference.
        monkeypatch.setattr("refresh_task.worker.os.setsid", fake_setsid)

        # Provide enough mock context for the worker to no-op a render.
        from PIL import Image as _Image

        class _FakePlugin:
            def generate_image(self, settings, cfg):
                return _Image.new("RGB", (10, 10), "red")

        class _FakeAction:
            def execute(self, plugin, cfg, dt):
                return plugin.generate_image(None, cfg)

        from unittest.mock import MagicMock

        with (
            patch(
                "refresh_task.worker.get_plugin_instance",
                return_value=_FakePlugin(),
            ),
            patch(
                "refresh_task.worker._restore_child_config",
                return_value=MagicMock(),
            ),
        ):
            _execute_refresh_attempt_worker(
                _queue.Queue(),
                {"id": "test"},
                _FakeAction(),
                MagicMock(),
                datetime.now(UTC),
            )

        assert called, (
            "worker did not call os.setsid() — chromium descendants will "
            "leak when the parent's _cleanup_subprocess only signals the "
            "worker pid (JTN-S2 regression)"
        )

    def test_worker_setsid_eperm_is_swallowed(self, monkeypatch):
        """If setsid fails (already a session leader, e.g. under some test
        mocks), the worker must still complete its render — the signal
        propagation path is best-effort, not load-bearing."""
        import queue as _queue

        from refresh_task import _execute_refresh_attempt_worker

        def setsid_eperm():
            raise OSError(1, "Operation not permitted")

        monkeypatch.setattr("refresh_task.worker.os.setsid", setsid_eperm)

        from PIL import Image as _Image

        class _FakePlugin:
            def generate_image(self, settings, cfg):
                return _Image.new("RGB", (10, 10), "blue")

        class _FakeAction:
            def execute(self, plugin, cfg, dt):
                return plugin.generate_image(None, cfg)

        q = _queue.Queue()
        from unittest.mock import MagicMock

        with (
            patch(
                "refresh_task.worker.get_plugin_instance",
                return_value=_FakePlugin(),
            ),
            patch(
                "refresh_task.worker._restore_child_config",
                return_value=MagicMock(),
            ),
        ):
            _execute_refresh_attempt_worker(
                q,
                {"id": "test"},
                _FakeAction(),
                MagicMock(),
                datetime.now(UTC),
            )
        payload = q.get_nowait()
        assert payload["ok"] is True
        os.unlink(payload["image_path"])

    def test_cleanup_subprocess_killpgs_unconditionally_before_terminate(
        self, monkeypatch
    ):
        """JTN-S2 regression: cleanup must call ``killpg(SIGKILL)`` BEFORE
        the terminate/alive dance, not gated behind ``proc.is_alive()``.

        On the device, a worker that exits cleanly on SIGTERM would
        leave the killpg branch unreached — which was the original
        9-process-per-timeout leak.  Pinning the unconditional ordering
        keeps that bug from coming back.
        """
        import signal as _signal

        from refresh_task import RefreshTask

        killpg_calls: list[tuple[int, int]] = []
        events: list[str] = []

        def fake_getpgid(pid):
            # Returning a non-zero pgid distinct from getpgid(0) so the
            # production code's ``pgid != os.getpgid(0)`` guard passes.
            return 99999 if pid != 0 else 1

        def fake_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))
            events.append("killpg")

        monkeypatch.setattr("refresh_task.task.os.getpgid", fake_getpgid)
        monkeypatch.setattr("refresh_task.task.os.killpg", fake_killpg)

        # Worker that exits gracefully on terminate() (the case that
        # used to bypass the killpg branch).
        class GracefulProc:
            pid = 12345

            def terminate(self):
                events.append("terminate")

            def join(self, timeout=None):
                events.append("join")

            def is_alive(self):
                return False  # dies cleanly on SIGTERM

            def kill(self):  # pragma: no cover  should not be reached
                events.append("kill")

        proc = GracefulProc()
        RefreshTask._cleanup_subprocess(proc, "graceful-plugin")

        assert killpg_calls, (
            "killpg never fired — chromium descendants leak when the "
            "worker exits cleanly on SIGTERM (JTN-S2 regression)"
        )
        pgid, sig = killpg_calls[0]
        assert pgid == 99999, f"expected killpg on worker pgid 99999; got {pgid}"
        assert sig == _signal.SIGKILL, (
            f"expected SIGKILL to the group; got {sig}. SIGTERM is "
            "insufficient — chromium renderers ignore it under memory "
            "pressure."
        )
        # Critical ordering: killpg MUST come before terminate so the
        # group is taken down even when the worker is graceful.
        assert events.index("killpg") < events.index(
            "terminate"
        ), f"killpg must precede terminate; saw {events}"


# ---------------------------------------------------------------------------
# Orphan render tempfile sweep
# ---------------------------------------------------------------------------


class TestSweepOrphanRenderTempfiles:
    """Guards the cleanup that runs at service start.

    The pipe-buffer fix writes a PNG tempfile in the child and unlinks it
    in the parent.  If the parent crashes between read and unlink (or
    terminates the child before it can put), the tempfile leaks.  The
    sweep prevents indefinite accumulation on disk-backed ``/tmp`` setups.
    """

    def _patch_tmpdir(self, monkeypatch, path):
        # ``tempfile.gettempdir`` caches; clear that cache so each test
        # picks up the patched env-var ``TMPDIR``.
        monkeypatch.setattr("tempfile.tempdir", str(path))

    def test_deletes_old_files_only(self, tmp_path, monkeypatch):
        from refresh_task.worker import sweep_orphan_render_tempfiles

        self._patch_tmpdir(monkeypatch, tmp_path)

        old = tmp_path / "inkypi_render_old.png"
        old.write_bytes(b"x" * 100)
        new = tmp_path / "inkypi_render_new.png"
        new.write_bytes(b"x" * 200)
        unrelated = tmp_path / "something_else.png"
        unrelated.write_bytes(b"x" * 50)

        # Backdate `old` to 2 hours ago.
        two_hours_ago = time.time() - 7200
        os.utime(old, (two_hours_ago, two_hours_ago))

        deleted, freed = sweep_orphan_render_tempfiles(max_age_seconds=3600)

        assert deleted == 1
        assert freed == 100
        assert not old.exists()
        assert new.exists(), "in-flight render must not be touched"
        assert unrelated.exists(), "non-inkypi files must not be touched"

    def test_returns_zero_when_directory_empty(self, tmp_path, monkeypatch):
        from refresh_task.worker import sweep_orphan_render_tempfiles

        self._patch_tmpdir(monkeypatch, tmp_path)
        deleted, freed = sweep_orphan_render_tempfiles()
        assert (deleted, freed) == (0, 0)

    def test_unlink_failure_continues_sweep(self, tmp_path, monkeypatch):
        from refresh_task.worker import sweep_orphan_render_tempfiles

        self._patch_tmpdir(monkeypatch, tmp_path)
        a = tmp_path / "inkypi_render_a.png"
        b = tmp_path / "inkypi_render_b.png"
        for f in (a, b):
            f.write_bytes(b"x")
            os.utime(f, (time.time() - 7200, time.time() - 7200))

        # Make `a.unlink` fail (simulate a permission/race) — sweep must
        # still process `b`.
        real_unlink = os.unlink

        def flaky_unlink(path, *args, **kwargs):
            if path == str(a):
                raise PermissionError("simulated")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr("refresh_task.worker.os.unlink", flaky_unlink)
        deleted, _ = sweep_orphan_render_tempfiles()
        assert deleted == 1, "sweep must continue after a single-file unlink failure"
        assert a.exists()
        assert not b.exists()


# ---------------------------------------------------------------------------
# RefreshTask.stop()
# ---------------------------------------------------------------------------


class TestRefreshTaskStop:
    def _make_task(self, device_config_dev):
        dm = MagicMock()
        return RefreshTask(device_config_dev, dm)

    def test_stop_rejects_pending_requests(self, device_config_dev):
        task = self._make_task(device_config_dev)
        task.running = True

        req1 = ManualUpdateRequest("r1", MagicMock())
        req2 = ManualUpdateRequest("r2", MagicMock())
        task.manual_update_requests.append(req1)
        task.manual_update_requests.append(req2)

        task.stop()

        assert task.running is False
        assert req1.done.is_set()
        assert req2.done.is_set()
        assert isinstance(req1.exception, RuntimeError)
        assert isinstance(req2.exception, RuntimeError)

    def test_stop_when_not_running(self, device_config_dev):
        """stop() on an already-stopped task should not raise."""
        task = self._make_task(device_config_dev)
        task.running = False
        task.stop()  # should not raise

    def test_stop_joins_thread(self, device_config_dev):
        task = self._make_task(device_config_dev)
        task.running = True

        # Create a thread that exits immediately
        done_event = threading.Event()

        def _quick():
            done_event.wait(timeout=5)

        task.thread = threading.Thread(target=_quick, daemon=True)
        task.thread.start()
        done_event.set()

        task.stop()
        assert not task.thread.is_alive()


# ---------------------------------------------------------------------------
# _execute_with_policy — error paths via mocked Process
# ---------------------------------------------------------------------------


class TestExecuteWithPolicyErrors:
    def _make_task(self, device_config_dev):
        dm = MagicMock()
        task = RefreshTask(device_config_dev, dm)
        task.running = True
        return task

    @staticmethod
    def _mock_action():
        action = MagicMock()
        action.get_plugin_id.return_value = "test_plugin"
        return action

    def test_empty_queue_zero_exit_raises(self, device_config_dev):
        """Process exits cleanly but puts nothing in queue."""
        task = self._make_task(device_config_dev)

        fake_proc = MagicMock()
        fake_proc.is_alive.return_value = False
        fake_proc.exitcode = 0
        fake_queue = MagicMock()
        fake_queue.get_nowait.side_effect = queue.Empty

        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        with (
            patch("refresh_task.task._get_mp_context", return_value=ctx),
            patch.dict(os.environ, {"INKYPI_PLUGIN_ISOLATION": "process"}),
        ):
            try:
                task._execute_with_policy(
                    self._mock_action(),
                    {"id": "test"},
                    datetime.now(UTC),
                    "req-1",
                )
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                assert "without returning a result" in str(e)

    def test_empty_queue_nonzero_exit_raises(self, device_config_dev):
        """Process crashes (exit code != 0) and puts nothing in queue."""
        task = self._make_task(device_config_dev)

        fake_proc = MagicMock()
        fake_proc.is_alive.return_value = False
        fake_proc.exitcode = -9
        fake_queue = MagicMock()
        fake_queue.get_nowait.side_effect = queue.Empty

        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        with (
            patch("refresh_task.task._get_mp_context", return_value=ctx),
            patch.dict(os.environ, {"INKYPI_PLUGIN_ISOLATION": "process"}),
        ):
            try:
                task._execute_with_policy(
                    self._mock_action(),
                    {"id": "test"},
                    datetime.now(UTC),
                    "req-1",
                )
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                assert "exited with code -9" in str(e)

    def test_error_payload_raises_remote_exception(self, device_config_dev):
        """Process returns an error payload — should reconstruct the exception."""
        task = self._make_task(device_config_dev)

        fake_proc = MagicMock()
        fake_proc.is_alive.return_value = False
        fake_proc.exitcode = 0
        fake_queue = MagicMock()
        fake_queue.get_nowait.return_value = {
            "ok": False,
            "error_type": "ValueError",
            "error_message": "bad input",
        }

        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        with (
            patch("refresh_task.task._get_mp_context", return_value=ctx),
            patch.dict(os.environ, {"INKYPI_PLUGIN_ISOLATION": "process"}),
        ):
            try:
                task._execute_with_policy(
                    self._mock_action(),
                    {"id": "test"},
                    datetime.now(UTC),
                    "req-1",
                )
                assert False, "Expected ValueError"
            except ValueError as e:
                assert "bad input" in str(e)

    def test_timeout_terminates_process(self, device_config_dev):
        """Process hangs past timeout — should terminate and raise TimeoutError."""
        task = self._make_task(device_config_dev)

        fake_proc = MagicMock()
        # is_alive: True after join (still running), then False after terminate+join
        # Provide extra False values for any additional checks
        fake_proc.is_alive.side_effect = [True, False, False, False]
        fake_proc.exitcode = None
        fake_proc.pid = 12345
        fake_queue = MagicMock()

        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        with (
            patch("refresh_task.task._get_mp_context", return_value=ctx),
            patch.dict(
                os.environ,
                {
                    "INKYPI_PLUGIN_ISOLATION": "process",
                    "INKYPI_PLUGIN_RETRY_MAX": "0",
                },
            ),
        ):
            try:
                task._execute_with_policy(
                    self._mock_action(),
                    {"id": "test"},
                    datetime.now(UTC),
                    "req-1",
                )
                assert False, "Expected TimeoutError"
            except TimeoutError as e:
                assert "timed out" in str(e)
            fake_proc.terminate.assert_called_once()

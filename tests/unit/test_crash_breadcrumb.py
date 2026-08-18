"""Crash breadcrumbs and crash quarantine.

The circuit breaker counts *handled* exceptions. A plugin that gets the process
OOM-killed or segfaults raises nothing catchable, so it never trips the breaker
— it just crash-loops, and the in-memory failure count dies with the process so
the streak never accumulates either. These two mechanisms close that hole: the
breadcrumb records what was in flight, and the quarantine acts on it.
"""

from __future__ import annotations

import pytest

from refresh_task.health import PluginHealthTracker
from utils import crash_breadcrumb


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Point both the tmpfs-backed and persistent paths at a tmpdir."""
    runtime = tmp_path / "run"
    state = tmp_path / "state"
    runtime.mkdir()
    state.mkdir()
    monkeypatch.setenv("INKYPI_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(state))
    return runtime, state


class TestBreadcrumbLifecycle:
    def test_clean_run_leaves_nothing_behind(self):
        with crash_breadcrumb.trail("refresh", plugin_id="clock", instance="a"):
            pass
        assert crash_breadcrumb.examine_boot() is None

    def test_handled_exception_still_clears_the_breadcrumb(self):
        """A raised exception was handled — that is the breaker's job, not ours."""
        with pytest.raises(RuntimeError):
            with crash_breadcrumb.trail("refresh", plugin_id="clock", instance="a"):
                raise RuntimeError("plugin blew up but we caught it")
        assert crash_breadcrumb.examine_boot() is None

    def test_hard_kill_leaves_the_breadcrumb_for_the_next_start(self):
        # A hard kill runs no finally block, so simulate by dropping only.
        crash_breadcrumb.drop("refresh", plugin_id="ai_image", instance="daily")

        found = crash_breadcrumb.examine_boot()

        assert found is not None
        assert found["operation"] == "refresh"
        assert found["plugin_id"] == "ai_image"
        assert found["instance"] == "daily"
        assert "started_at" in found

    def test_examine_boot_is_idempotent(self):
        """A second start must not re-attribute a death it already consumed."""
        crash_breadcrumb.drop("refresh", plugin_id="ai_image", instance="daily")
        assert crash_breadcrumb.examine_boot() is not None
        assert crash_breadcrumb.examine_boot() is None

    def test_death_is_persisted_and_counted(self):
        crash_breadcrumb.drop("refresh", plugin_id="ai_image", instance="daily")
        crash_breadcrumb.examine_boot()

        death = crash_breadcrumb.last_death()
        assert death is not None
        assert death["plugin_id"] == "ai_image"
        assert crash_breadcrumb.death_count() == 1

        crash_breadcrumb.drop("refresh", plugin_id="weather", instance="home")
        crash_breadcrumb.examine_boot()
        assert crash_breadcrumb.death_count() == 2
        assert crash_breadcrumb.last_death()["plugin_id"] == "weather"

    def test_clear_last_death_forgets_the_record(self):
        crash_breadcrumb.drop("refresh", plugin_id="ai_image", instance="daily")
        crash_breadcrumb.examine_boot()
        crash_breadcrumb.clear_last_death()
        assert crash_breadcrumb.last_death() is None
        assert crash_breadcrumb.death_count() == 0

    def test_corrupt_breadcrumb_is_survivable(self, isolated_dirs):
        runtime, _ = isolated_dirs
        (runtime / "breadcrumb.json").write_text("{not json")
        # Must not raise, and must clear the bad file so it cannot loop.
        assert crash_breadcrumb.examine_boot() is None
        assert not (runtime / "breadcrumb.json").exists()

    def test_unwritable_paths_never_raise(self, monkeypatch):
        """Forensics must never be why a refresh fails."""
        monkeypatch.setenv("INKYPI_RUNTIME_DIR", "/proc/definitely/not/writable")
        crash_breadcrumb.drop("refresh", plugin_id="clock")
        crash_breadcrumb.clear()
        assert crash_breadcrumb.examine_boot() is None


class _FakeInstance:
    def __init__(self):
        self.paused = False
        self.consecutive_failure_count = 0
        self.disabled_reason = None


class _FakePlaylistManager:
    def __init__(self, instances):
        self._instances = instances

    def find_plugin(self, plugin_id, instance_name):
        return self._instances.get((plugin_id, instance_name))


class _FakeConfig:
    def __init__(self, instances):
        self.playlist_manager = _FakePlaylistManager(instances)
        self.writes = 0

    def get_playlist_manager(self):
        return self.playlist_manager

    def get_config(self, key, default=None):
        return default

    def write_config(self):
        self.writes += 1


class TestCrashQuarantine:
    def _tracker(self, instances):
        config = _FakeConfig(instances)
        return PluginHealthTracker(device_config=config), config

    def test_pauses_the_plugin_that_was_in_flight(self):
        instance = _FakeInstance()
        tracker, config = self._tracker({("ai_image", "daily"): instance})

        quarantined = tracker.quarantine_after_crash(
            {
                "operation": "refresh",
                "plugin_id": "ai_image",
                "instance": "daily",
                "started_at": "2026-08-15T00:00:00+00:00",
            }
        )

        assert quarantined is True
        assert instance.paused is True
        assert "died while this plugin was rendering" in instance.disabled_reason
        assert config.writes == 1, "the pause must be persisted"

    def test_is_a_noop_without_an_instance_name(self):
        """Pausing every instance of a plugin would be too blunt a response."""
        instance = _FakeInstance()
        tracker, _ = self._tracker({("ai_image", "daily"): instance})

        assert tracker.quarantine_after_crash({"plugin_id": "ai_image"}) is False
        assert instance.paused is False

    def test_is_a_noop_for_an_unknown_instance(self):
        tracker, config = self._tracker({})
        assert (
            tracker.quarantine_after_crash(
                {"plugin_id": "ghost", "instance": "missing"}
            )
            is False
        )
        assert config.writes == 0

    def test_does_not_re_pause_an_already_paused_instance(self):
        instance = _FakeInstance()
        instance.paused = True
        instance.disabled_reason = "Paused by the user"
        tracker, config = self._tracker({("ai_image", "daily"): instance})

        assert (
            tracker.quarantine_after_crash(
                {"plugin_id": "ai_image", "instance": "daily"}
            )
            is False
        )
        # The existing reason must survive — it may be a deliberate user pause.
        assert instance.disabled_reason == "Paused by the user"
        assert config.writes == 0

    def test_quarantine_can_be_lifted_by_the_normal_reset_path(self):
        """Re-enabling must work through the existing UI/API plumbing."""
        instance = _FakeInstance()
        tracker, _ = self._tracker({("ai_image", "daily"): instance})
        tracker.quarantine_after_crash({"plugin_id": "ai_image", "instance": "daily"})
        assert instance.paused is True

        assert tracker.reset_circuit_breaker("ai_image", "daily") is True
        assert instance.paused is False
        assert instance.disabled_reason is None

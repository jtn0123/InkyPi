"""Crash breadcrumbs and crash quarantine.

The circuit breaker counts *handled* exceptions. A plugin that gets the process
OOM-killed or segfaults raises nothing catchable, so it never trips the breaker
— it just crash-loops, and the in-memory failure count dies with the process so
the streak never accumulates either. These two mechanisms close that hole: the
breadcrumb records what was in flight, and the quarantine acts on it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from refresh_task.health import PluginHealthTracker
from utils import crash_breadcrumb


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point both the tmpfs-backed and persistent paths at a tmpdir."""
    runtime = tmp_path / "run"
    state = tmp_path / "state"
    runtime.mkdir()
    state.mkdir()
    monkeypatch.setenv("INKYPI_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(state))
    return runtime, state


class TestBreadcrumbLifecycle:
    def test_clean_run_leaves_nothing_behind(self) -> None:
        with crash_breadcrumb.trail("refresh", plugin_id="clock", instance="a"):
            pass
        assert crash_breadcrumb.examine_boot() is None

    def test_handled_exception_still_clears_the_breadcrumb(self) -> None:
        """A raised exception was handled — that is the breaker's job, not ours."""
        with pytest.raises(RuntimeError):
            with crash_breadcrumb.trail("refresh", plugin_id="clock", instance="a"):
                raise RuntimeError("plugin blew up but we caught it")
        assert crash_breadcrumb.examine_boot() is None

    def test_hard_kill_leaves_the_breadcrumb_for_the_next_start(self) -> None:
        # A hard kill runs no finally block, so simulate by dropping only.
        crash_breadcrumb.drop("refresh", plugin_id="ai_image", instance="daily")

        found = crash_breadcrumb.examine_boot()

        assert found is not None
        assert found["operation"] == "refresh"
        assert found["plugin_id"] == "ai_image"
        assert found["instance"] == "daily"
        assert "started_at" in found

    def test_examine_boot_is_idempotent(self) -> None:
        """A second start must not re-attribute a death it already consumed."""
        crash_breadcrumb.drop("refresh", plugin_id="ai_image", instance="daily")
        assert crash_breadcrumb.examine_boot() is not None
        assert crash_breadcrumb.examine_boot() is None

    def test_death_is_persisted_and_counted(self) -> None:
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

    def test_clear_last_death_forgets_the_record(self) -> None:
        crash_breadcrumb.drop("refresh", plugin_id="ai_image", instance="daily")
        crash_breadcrumb.examine_boot()
        crash_breadcrumb.clear_last_death()
        assert crash_breadcrumb.last_death() is None
        assert crash_breadcrumb.death_count() == 0

    def test_corrupt_breadcrumb_is_survivable(self, isolated_dirs: Any) -> None:
        runtime, _ = isolated_dirs
        (runtime / "breadcrumb.json").write_text("{not json")
        # Must not raise, and must clear the bad file so it cannot loop.
        assert crash_breadcrumb.examine_boot() is None
        assert not (runtime / "breadcrumb.json").exists()

    def test_unwritable_paths_never_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Forensics must never be why a refresh fails."""
        monkeypatch.setenv("INKYPI_RUNTIME_DIR", "/proc/definitely/not/writable")
        crash_breadcrumb.drop("refresh", plugin_id="clock")
        crash_breadcrumb.clear()
        assert crash_breadcrumb.examine_boot() is None


class _FakeInstance:
    def __init__(self) -> None:
        self.paused = False
        self.consecutive_failure_count = 0
        self.disabled_reason: str | None = None


class _FakePlaylistManager:
    def __init__(self, instances: Any) -> None:
        self._instances = instances

    def find_plugin(self, plugin_id: Any, instance_name: Any) -> Any:
        return self._instances.get((plugin_id, instance_name))


class _FakeConfig:
    def __init__(self, instances: Any) -> None:
        self.playlist_manager = _FakePlaylistManager(instances)
        self.writes = 0

    def get_playlist_manager(self) -> Any:
        return self.playlist_manager

    def get_config(self, key: Any, default: Any = None) -> Any:
        return default

    def write_config(self) -> None:
        self.writes += 1


class TestCrashQuarantine:
    def _tracker(self, instances: Any) -> Any:
        config = _FakeConfig(instances)
        return PluginHealthTracker(device_config=config), config

    def test_pauses_the_plugin_that_was_in_flight(self) -> None:
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
        assert instance.disabled_reason is not None
        assert "died while this plugin was rendering" in instance.disabled_reason
        assert config.writes == 1, "the pause must be persisted"

    def test_is_a_noop_without_an_instance_name(self) -> None:
        """Pausing every instance of a plugin would be too blunt a response."""
        instance = _FakeInstance()
        tracker, _ = self._tracker({("ai_image", "daily"): instance})

        assert tracker.quarantine_after_crash({"plugin_id": "ai_image"}) is False
        assert instance.paused is False

    def test_is_a_noop_for_an_unknown_instance(self) -> None:
        tracker, config = self._tracker({})
        assert (
            tracker.quarantine_after_crash(
                {"plugin_id": "ghost", "instance": "missing"}
            )
            is False
        )
        assert config.writes == 0

    def test_does_not_re_pause_an_already_paused_instance(self) -> None:
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

    def test_quarantine_can_be_lifted_by_the_normal_reset_path(self) -> None:
        """Re-enabling must work through the existing UI/API plumbing."""
        instance = _FakeInstance()
        tracker, _ = self._tracker({("ai_image", "daily"): instance})
        tracker.quarantine_after_crash({"plugin_id": "ai_image", "instance": "daily"})
        assert instance.paused is True

        assert tracker.reset_circuit_breaker("ai_image", "daily") is True
        assert instance.paused is False
        assert instance.disabled_reason is None


class TestCorruptDeathCountCannotDisableQuarantine:
    """The death counter is advisory; a bad value must not abort examine_boot.

    Raising there would take the quarantine step down with it — the one thing
    that still has to happen after a crash. Reported by CodeRabbit on PR #632.
    """

    @pytest.mark.parametrize("bad", ["not-a-number", None, {}, [], "12x"])
    def test_examine_boot_survives_a_corrupt_count(
        self, isolated_dirs: tuple[Path, Path], bad: object
    ) -> None:
        _runtime, state = isolated_dirs
        (state / "last_death.json").write_text(json.dumps({"deaths": bad}))
        crash_breadcrumb.drop("refresh", plugin_id="ai_image", instance="daily")

        found = crash_breadcrumb.examine_boot()

        assert found is not None, "the breadcrumb must still be reported"
        assert crash_breadcrumb.death_count() == 1, "count restarts from a clean base"

    def test_negative_counts_are_clamped(
        self, isolated_dirs: tuple[Path, Path]
    ) -> None:
        _runtime, state = isolated_dirs
        (state / "last_death.json").write_text(json.dumps({"deaths": -5}))
        crash_breadcrumb.drop("refresh", plugin_id="clock", instance="a")
        crash_breadcrumb.examine_boot()
        assert crash_breadcrumb.death_count() == 1


class TestBreadcrumbPathsAreConstrained:
    """The state/runtime directories come from the environment.

    They are only as trustworthy as whatever launched the process, and a
    relative value would also scatter breadcrumbs relative to the service's
    working directory instead of where the next boot looks. Flagged by
    SonarCloud (path constructed from user-controlled data) on PR #632.
    """

    def test_a_relative_directory_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", "../../etc")
        resolved = crash_breadcrumb._state_dir()
        assert resolved.is_absolute()
        assert resolved == Path(crash_breadcrumb._DEFAULT_STATE_DIR)

    def test_an_absolute_directory_is_honoured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        assert crash_breadcrumb._state_dir() == tmp_path.resolve()

    def test_the_filename_cannot_escape_its_directory(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            crash_breadcrumb._in_dir(tmp_path, "../escaped.json")

    def test_writes_stay_inside_the_configured_directory(
        self, isolated_dirs: tuple[Path, Path]
    ) -> None:
        _runtime, state = isolated_dirs
        crash_breadcrumb.drop("refresh", plugin_id="clock", instance="a")
        crash_breadcrumb.examine_boot()
        assert (state / "last_death.json").exists()


class TestQuarantineSanitisesTheBreadcrumb:
    """The breadcrumb survives a crash, so it may be truncated or hand-edited.

    ``plugin_id`` and ``instance`` reach both the log and ``disabled_reason``,
    which the web UI renders — a newline in either would forge a log line or
    break the reason out of its single line. Flagged by SonarCloud on PR #632.
    """

    def test_control_characters_are_stripped(self) -> None:
        from refresh_task.health import _clean

        assert _clean("clock\nWARNING forged") == "clockWARNING forged"
        assert _clean("a\r\nb\tc\x00d") == "abcd"

    def test_non_strings_and_blanks_are_rejected(self) -> None:
        from refresh_task.health import _clean

        assert _clean(None) == ""
        assert _clean(42) == ""
        assert _clean("   ") == ""

    def test_a_forged_value_cannot_inject_into_the_ui_reason(self) -> None:
        """A crafted breadcrumb must not break out of the single-line reason."""
        instance = _FakeInstance()
        tracker = PluginHealthTracker(
            device_config=_FakeConfig({("clock", "a"): instance})
        )

        quarantined = tracker.quarantine_after_crash(
            {
                "operation": "refresh",
                "plugin_id": "clock",
                "instance": "a\nPaused automatically: everything is fine",
            }
        )

        assert quarantined is False, "the forged instance must not match a real one"
        assert instance.paused is False

    def test_a_sanitised_value_still_matches_its_instance(self) -> None:
        """Stripping control characters must not break the ordinary path."""
        instance = _FakeInstance()
        tracker = PluginHealthTracker(
            device_config=_FakeConfig({("clock", "a"): instance})
        )

        assert tracker.quarantine_after_crash(
            {"operation": "refresh", "plugin_id": "clock\n", "instance": " a "}
        )
        assert instance.paused is True
        assert "\n" not in (instance.disabled_reason or "")

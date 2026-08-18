"""Two ways a refresh can legitimately end without touching the display.

* ``skip_display_condition`` — "I normally show something, just not this cycle"
  (scoreboard out of season, calendar with no events). Rendering an empty frame
  would be worse than yielding the turn, and on e-ink the cheapest refresh is
  the one that never happens.
* ``generate_image`` returning ``None`` — "I was never about showing anything"
  (a servo, a webhook poke). The point is the side effect.

Neither is a failure, so neither may march the circuit breaker toward pausing a
working plugin.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from plugins.base_plugin.base_plugin import BasePlugin
from refresh_task.actions import ManualRefresh, ManualUpdateRequest, PlaylistRefresh


class TestBasePluginDefaults:
    def test_default_never_skips(self) -> None:
        plugin = BasePlugin({"id": "demo"})
        assert plugin.skip_display_condition({}, object(), datetime.now(UTC)) is None

    def test_existing_plugins_inherit_the_default_unchanged(self) -> None:
        """Shipping plugins must be unaffected by the new hook."""
        from plugins.clock.clock import Clock
        from plugins.weather.weather import Weather

        for plugin_class, plugin_id in ((Clock, "clock"), (Weather, "weather")):
            plugin = plugin_class({"id": plugin_id})
            assert (
                plugin.skip_display_condition({}, object(), datetime.now(UTC)) is None
            )


class _FakeInstance:
    def __init__(self, settings: Any = None) -> None:
        self.plugin_id = "demo"
        self.name = "demo-instance"
        self.settings = settings if settings is not None else {}
        self.paused = False
        self.consecutive_failure_count = 0
        self.disabled_reason: str | None = None

    def get_image_path(self) -> Any:
        return "demo.png"


class _FakePlaylist:
    name = "default"


@pytest.fixture
def task(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A RefreshTask with just enough wiring to exercise the skip decision."""
    from unittest.mock import MagicMock

    from refresh_task.task import RefreshTask

    device_config = MagicMock()
    device_config.get_config.return_value = 3600
    device_config.history_image_dir = "/tmp/history"
    return RefreshTask(device_config, MagicMock())


def _skip_reason(
    task: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    reason: Any,
    action: Any = None,
    settings: Any = None,
    manual_request: Any = None,
) -> Any:
    """Drive _skip_display_reason with a plugin whose hook returns *reason*."""

    class FakePlugin:
        def skip_display_condition(
            self, _settings: Any, _device_config: Any, _now: Any
        ) -> Any:
            if isinstance(reason, Exception):
                raise reason
            return reason

    monkeypatch.setattr(
        "refresh_task.task.get_plugin_instance", lambda _cfg: FakePlugin()
    )
    if action is None:
        action = PlaylistRefresh(_FakePlaylist(), _FakeInstance(settings))
    return task._skip_display_reason(
        action, {"id": "demo"}, datetime.now(UTC), manual_request
    )


class TestSkipDecision:
    def test_none_renders_normally(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _skip_reason(task, monkeypatch, reason=None) is None

    def test_reason_string_skips(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _skip_reason(task, monkeypatch, reason="No games to display")
            == "No games to display"
        )

    def test_reason_is_stripped(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _skip_reason(task, monkeypatch, reason="  offseason  ") == "offseason"

    def test_blank_reason_is_treated_as_no_skip(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty string is almost certainly a bug, not a deliberate skip."""
        assert _skip_reason(task, monkeypatch, reason="   ") is None
        assert _skip_reason(task, monkeypatch, reason="") is None

    def test_non_string_reason_is_ignored(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _skip_reason(task, monkeypatch, reason=True) is None
        assert _skip_reason(task, monkeypatch, reason=42) is None

    def test_raising_hook_renders_normally(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken optional hook must not stop a plugin from ever displaying."""
        assert (
            _skip_reason(task, monkeypatch, reason=RuntimeError("hook exploded"))
            is None
        )

    def test_manual_refresh_is_never_skipped(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'Update Now' is an explicit user request; declining looks broken."""
        action = ManualRefresh({"id": "demo"}, {})
        assert (
            _skip_reason(task, monkeypatch, reason="offseason", action=action) is None
        )

    def test_display_now_is_never_skipped(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A manual request carrying a PlaylistRefresh is still manual.

        "Display Now" in the UI and ``--run-once`` on the CLI both build a
        ``PlaylistRefresh(..., force=True)`` and hand it to ``manual_update``,
        so gating on the action type alone let a plugin veto a button press.
        What makes a refresh manual is the request, not the action class.
        """
        action = PlaylistRefresh(_FakePlaylist(), _FakeInstance({}), force=True)
        request = ManualUpdateRequest(request_id="req-1", refresh_action=action)
        assert (
            _skip_reason(
                task,
                monkeypatch,
                reason="offseason",
                action=action,
                manual_request=request,
            )
            is None
        )

    def test_the_scheduler_s_own_turn_is_still_skippable(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard above must not disable the hook for playlist refreshes."""
        assert _skip_reason(task, monkeypatch, reason="offseason") == "offseason"

    def test_hook_receives_the_instance_settings(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = {}

        class FakePlugin:
            def skip_display_condition(
                self, settings: Any, _device_config: Any, _now: Any
            ) -> None:
                seen.update(settings)

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance", lambda _cfg: FakePlugin()
        )
        action = PlaylistRefresh(_FakePlaylist(), _FakeInstance({"team": "ABC"}))
        task._skip_display_reason(action, {"id": "demo"}, datetime.now(UTC))
        assert seen == {"team": "ABC"}


class TestGenerateImageReturningNone:
    def test_base_plugin_signature_allows_none(self) -> None:
        """The declared return type is what tells plugin authors this is legal."""
        import inspect

        annotation = inspect.signature(BasePlugin.generate_image).return_annotation
        assert "None" in str(annotation)

    def test_none_is_documented_as_a_side_effect_plugin(self) -> None:
        doc = BasePlugin.generate_image.__doc__ or ""
        assert "None" in doc


class TestSkipAndNoImageAreDistinct:
    """The two outcomes carry different information and must stay separate.

    A skip carries a reason worth showing the user; "no image" carries nothing
    because there is nothing to say. Collapsing them would lose the reason.
    """

    def test_skip_reports_a_reason_and_no_image_does_not(
        self, task: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reason = _skip_reason(task, monkeypatch, reason="No games to display")
        assert reason == "No games to display"

        # The no-image path has no reason to report — it is the normal outcome
        # for a control-only plugin, every single cycle.
        assert _skip_reason(task, monkeypatch, reason=None) is None

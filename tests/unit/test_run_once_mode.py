"""``--run-once``: render the next playlist plugin, push it, exit.

A distinct operating mode rather than a variant of the normal one — nothing
listens on a port and no scheduler loop runs — so a very low duty-cycle frame
can be driven entirely by cron or a systemd timer.

Cron needs a real exit status to alert on, so every failure path here must
return non-zero rather than logging and exiting successfully.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import inkypi


class _FakePlaylist:
    def __init__(self, plugin_instance: Any) -> None:
        self.name = "default"
        self._plugin_instance = plugin_instance

    def get_next_eligible_plugin(self, _current_dt: Any) -> Any:
        return self._plugin_instance


class _FakePluginInstance:
    plugin_id = "clock"
    name = "clock-a"


def _app(*, playlist: Any, refresh_task: Any) -> Any:
    app = MagicMock()
    device_config = MagicMock()
    playlist_manager = MagicMock()
    playlist_manager.determine_active_playlist.return_value = playlist
    device_config.get_playlist_manager.return_value = playlist_manager
    config = {"DEVICE_CONFIG": device_config, "REFRESH_TASK": refresh_task}
    app.config = config
    return app


class TestRunOnce:
    def test_refreshes_the_next_plugin_and_succeeds(self) -> None:
        refresh_task = MagicMock()
        playlist = _FakePlaylist(_FakePluginInstance())

        assert inkypi.run_once(_app(playlist=playlist, refresh_task=refresh_task)) == 0

        assert refresh_task.start.called, "the refresh loop owns the display"
        assert refresh_task.manual_update.call_count == 1
        action = refresh_task.manual_update.call_args[0][0]
        assert action.plugin_instance.plugin_id == "clock"
        assert action.force is True

    def test_stops_the_refresh_task_before_returning(self) -> None:
        """Nothing should be left running — the process is about to exit."""
        refresh_task = MagicMock()
        playlist = _FakePlaylist(_FakePluginInstance())

        inkypi.run_once(_app(playlist=playlist, refresh_task=refresh_task))

        assert refresh_task.stop.called

    def test_stops_the_refresh_task_even_when_the_refresh_raises(self) -> None:
        refresh_task = MagicMock()
        refresh_task.manual_update.side_effect = RuntimeError("plugin exploded")
        playlist = _FakePlaylist(_FakePluginInstance())

        assert inkypi.run_once(_app(playlist=playlist, refresh_task=refresh_task)) == 1
        assert refresh_task.stop.called

    def test_no_active_playlist_is_a_failure(self) -> None:
        refresh_task = MagicMock()
        assert inkypi.run_once(_app(playlist=None, refresh_task=refresh_task)) == 1
        assert not refresh_task.manual_update.called

    def test_no_eligible_plugin_is_a_failure(self) -> None:
        refresh_task = MagicMock()
        playlist = _FakePlaylist(None)
        assert inkypi.run_once(_app(playlist=playlist, refresh_task=refresh_task)) == 1
        assert not refresh_task.manual_update.called

    def test_missing_core_services_is_a_failure(self) -> None:
        app = MagicMock()
        app.config = {"DEVICE_CONFIG": None, "REFRESH_TASK": None}
        assert inkypi.run_once(app) == 1


class TestRunOnceFlag:
    def test_flag_is_accepted_and_defaults_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(inkypi, "create_app", lambda: MagicMock())
        inkypi.main(["--web-only"])
        assert inkypi.args.run_once is False

        inkypi.main(["--web-only", "--run-once"])
        assert inkypi.args.run_once is True

    def test_help_documents_the_exit_status_contract(self) -> None:
        """The exit status is the whole point for a cron caller."""
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), pytest.raises(SystemExit):
            inkypi.main(["--help"])

        text = buffer.getvalue()
        assert "--run-once" in text
        assert "non-zero" in text

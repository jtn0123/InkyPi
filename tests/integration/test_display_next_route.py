import time
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from blueprints.main import _reset_display_next_cooldown
from utils.domain_errors import PluginRenderFailed


def _fixed_now(_device_config: Any) -> Any:
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC)


def _add_playlist_with_plugin(device_config: Any) -> None:
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config.write_config()


def _add_empty_playlist(device_config: Any) -> None:
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    device_config.write_config()


@pytest.mark.integration
def test_display_next_returns_metrics(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> Any:
    flask_app.config["REFRESH_TASK"].running = False

    _add_playlist_with_plugin(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    from plugins import plugin_registry

    class _StubPlugin:
        def generate_image(self, settings: Any, device_config: Any) -> Any:
            return Image.new("RGB", (800, 480), "white")

    monkeypatch.setattr(
        plugin_registry, "get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )

    displayed = {"called": False}

    def _display_image(
        image: Any, image_settings: Any = None, history_meta: Any = None
    ) -> None:
        displayed["called"] = True

    flask_app.config["DISPLAY_MANAGER"].display_image = _display_image

    resp = client.post("/display-next")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("success") is True
    assert displayed["called"] is True
    metrics = body.get("metrics")
    assert isinstance(metrics, dict)
    for key in ("request_ms", "generate_ms", "preprocess_ms", "display_ms"):
        assert key in metrics
    assert metrics["generate_ms"] is not None


@pytest.mark.integration
def test_display_next_no_playlist_returns_error(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> None:
    flask_app.config["REFRESH_TASK"].running = False
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    pm = device_config_dev.get_playlist_manager()
    monkeypatch.setattr(pm, "determine_active_playlist", lambda dt: None, raising=True)

    resp = client.post("/display-next")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body.get("success") is False
    assert body.get("error") == "No active playlist"

    retry = client.post("/display-next")
    assert retry.status_code == 400
    assert retry.get_json()["error"] == "No active playlist"


@pytest.mark.integration
def test_display_next_no_plugin_returns_error(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> None:
    flask_app.config["REFRESH_TASK"].running = False
    _add_empty_playlist(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    resp = client.post("/display-next")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body.get("success") is False
    assert body.get("error") == "No eligible plugin to display"

    retry = client.post("/display-next")
    assert retry.status_code == 400
    assert retry.get_json()["error"] == "No eligible plugin to display"


@pytest.mark.integration
def test_display_next_direct_fits_a_wrong_size_image(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> Any:
    """The dev-path "display next" fits wrong-size output like the refresh task."""
    flask_app.config["REFRESH_TASK"].running = False
    _add_playlist_with_plugin(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    from plugins import plugin_registry

    class _StubPlugin:
        def generate_image(self, settings: Any, device_config: Any) -> Any:
            return Image.new("RGB", (1024, 676), "red")  # the APOD frame

    monkeypatch.setattr(
        plugin_registry, "get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )
    shown: list[Any] = []

    def _display_image(
        image: Any, image_settings: Any = None, history_meta: Any = None
    ) -> None:
        shown.append(image)

    flask_app.config["DISPLAY_MANAGER"].display_image = _display_image

    resp = client.post("/display-next")

    assert resp.status_code == 200
    assert [img.size for img in shown] == [(800, 480)]


@pytest.mark.integration
def test_display_next_does_not_repeat_the_write_on_a_type_error(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> None:
    """A TypeError from the driver used to trigger a second full panel write
    (and a second history entry) without ``history_meta``."""
    flask_app.config["REFRESH_TASK"].running = False
    _add_playlist_with_plugin(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    from plugins import plugin_registry

    class _StubPlugin:
        def generate_image(self, settings: Any, device_config: Any) -> Any:
            return Image.new("RGB", (800, 480), "white")

    monkeypatch.setattr(
        plugin_registry, "get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )
    calls: list[dict[str, Any]] = []

    def _display_image(image: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise TypeError("driver fault")

    monkeypatch.setattr(
        flask_app.config["DISPLAY_MANAGER"], "display_image", _display_image
    )

    resp = client.post("/display-next")

    assert resp.status_code == 500
    assert len(calls) == 1
    assert calls[0]["history_meta"]["plugin_instance"] == "Clock A"


_STALE_REFRESH_INFO = SimpleNamespace(
    request_ms=9999, generate_ms=9999, preprocess_ms=9999, display_ms=9999
)
_TIMING_CASES = [
    pytest.param(
        # manual_update returned at image_saved: the panel write is still going.
        {"generate_ms": None, "preprocess_ms": 42, "display_ms": None},
        {
            "request_ms": None,
            "generate_ms": None,
            "preprocess_ms": 42,
            "display_ms": None,
        },
        id="image-saved",
    ),
    pytest.param(
        {
            "request_ms": 120,
            "generate_ms": 80,
            "preprocess_ms": 30,
            "display_ms": 10,
            "steps": [["Generate", 80]],
        },
        {
            "request_ms": 120,
            "generate_ms": 80,
            "preprocess_ms": 30,
            "display_ms": 10,
            "steps": [["Generate", 80]],
        },
        id="completed",
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize(("returned", "expected"), _TIMING_CASES)
def test_display_next_reports_this_refreshs_timings(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
    returned: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    """The response used to read refresh_info, which still describes the
    previous refresh when manual_update returns at image_saved."""
    _add_playlist_with_plugin(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    refresh_task = flask_app.config["REFRESH_TASK"]
    monkeypatch.setattr(refresh_task, "running", True)
    monkeypatch.setattr(refresh_task, "manual_update", lambda action: returned)
    monkeypatch.setattr(
        device_config_dev, "get_refresh_info", lambda: _STALE_REFRESH_INFO
    )

    resp = client.post("/display-next")

    assert resp.status_code == 200
    assert resp.get_json()["metrics"] == expected


@pytest.fixture(autouse=True)
def _fresh_cooldown() -> Iterator[None]:
    _reset_display_next_cooldown()
    yield
    _reset_display_next_cooldown()


def _seed_clock_playlist(device_config_dev: Any) -> None:
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()


def test_refresh_alias_answers_like_display_next(client: FlaskClient) -> None:
    # The dev config's Default playlist starts with no plugins.
    resp = client.post("/refresh")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "No eligible plugin to display"
    # A failed attempt arms no cooldown.
    assert client.post("/refresh").status_code == 400


def test_success_shows_the_next_item_and_arms_the_cooldown(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _seed_clock_playlist(device_config_dev)

    resp = client.post("/display-next")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    shown = client.get("/refresh-info").get_json()
    assert shown["plugin_id"] == "clock"
    assert shown["plugin_instance"] == "Clock A"
    assert shown["playlist"] == "Default"

    blocked = client.post("/display-next")
    assert blocked.status_code == 429
    body = blocked.get_json()
    assert body["success"] is False
    assert body["error"].startswith("Please wait ")

    _reset_display_next_cooldown()
    assert client.post("/display-next").status_code == 200


def test_refresh_alias_shares_the_cooldown(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _seed_clock_playlist(device_config_dev)

    assert client.post("/refresh").status_code == 200
    assert client.post("/display-next").status_code == 429
    assert client.post("/refresh").status_code == 429


def test_cooldown_ends_after_ten_seconds(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_clock_playlist(device_config_dev)
    fake_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

    assert client.post("/display-next").status_code == 200

    fake_time[0] = 1005.0
    assert client.post("/display-next").status_code == 429

    fake_time[0] = 1011.0
    assert client.post("/display-next").status_code == 200


def _mock_playlist_manager() -> MagicMock:
    plugin_instance = MagicMock()
    plugin_instance.plugin_id = "test_plugin"
    plugin_instance.name = "Test"
    plugin_instance.settings = {}
    playlist = MagicMock()
    playlist.name = "Test Playlist"
    playlist.get_next_eligible_plugin.return_value = plugin_instance
    manager = MagicMock()
    manager.determine_active_playlist.return_value = playlist
    return manager


def test_render_failure_via_the_refresh_task_does_not_leak_detail(
    client: FlaskClient, flask_app: Flask, device_config_dev: Any
) -> None:
    secret_detail = "SECRET_STACKTRACE_DETAIL_abc123"
    refresh_task = flask_app.config["REFRESH_TASK"]
    with patch.object(
        device_config_dev,
        "get_playlist_manager",
        return_value=_mock_playlist_manager(),
    ):
        refresh_task.running = True
        # What the refresh cycle raises for a plugin's RuntimeError.
        refresh_task.manual_update = MagicMock(
            side_effect=PluginRenderFailed(secret_detail)
        )
        resp = client.post("/display-next")

    assert resp.status_code == 400
    body = resp.get_json()
    # Generic message only (CodeQL py/stack-trace-exposure).
    assert body["code"] == "plugin_error"
    assert body["error"] == "Plugin image generation failed"
    assert secret_detail not in resp.get_data(as_text=True)


def test_render_failure_in_the_request_does_not_leak_detail(
    client: FlaskClient, flask_app: Flask, device_config_dev: Any
) -> None:
    secret_detail = "LEAKY_RUNTIME_DETAIL_xyz789"
    plugin = MagicMock()
    plugin.generate_image.side_effect = RuntimeError(secret_detail)
    flask_app.config["REFRESH_TASK"].running = False

    with (
        patch.object(
            device_config_dev,
            "get_playlist_manager",
            return_value=_mock_playlist_manager(),
        ),
        patch.object(
            device_config_dev,
            "get_plugin",
            return_value={"id": "test_plugin", "image_settings": []},
        ),
        patch("plugins.plugin_registry.get_plugin_instance", return_value=plugin),
    ):
        resp = client.post("/display-next")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Plugin image generation failed"
    assert secret_detail not in resp.get_data(as_text=True)

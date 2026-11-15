from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image


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

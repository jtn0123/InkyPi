from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from PIL import Image

from refresh_task.actions import ManualRefresh, ManualUpdateRequest
from refresh_task.display_pipeline import DisplayPipeline
from refresh_task.housekeeping import RefreshHousekeeper
from refresh_task.recorder import RefreshRecorder


class _DisplayManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response: object = {
            "display_ms": 21,
            "preprocess_ms": 8,
            "display_driver": "mock",
        }
        self.exception: BaseException | None = None

    def display_image(
        self,
        image: Image.Image,
        image_settings: object = None,
        history_meta: dict[str, str | None] | None = None,
        on_image_saved: Any = None,
    ) -> object:
        self.calls.append(
            {
                "image": image,
                "image_settings": image_settings,
                "history_meta": history_meta,
                "on_image_saved": on_image_saved,
            }
        )
        if on_image_saved is not None:
            on_image_saved({"preprocess_ms": 8})
        if self.exception is not None:
            raise self.exception
        return self.response


def _make_pipeline(device_config_dev: Any, display_manager: _DisplayManager) -> tuple[
    DisplayPipeline,
    list[tuple[str, str | None, bool, Mapping[str, Any] | None, str | None]],
    list[tuple[str, str, int | None, Mapping[str, Any] | None]],
    list[dict[str, Any]],
]:
    housekeeper = RefreshHousekeeper(device_config_dev, display_manager)
    recorder = RefreshRecorder(device_config_dev)
    health_updates: list[
        tuple[str, str | None, bool, Mapping[str, Any] | None, str | None]
    ] = []
    stages: list[tuple[str, str, int | None, Mapping[str, Any] | None]] = []
    errors: list[dict[str, Any]] = []

    def update_health(
        plugin_id: str,
        instance: str | None,
        ok: bool,
        metrics: Mapping[str, Any] | None,
        error: str | None,
    ) -> None:
        health_updates.append((plugin_id, instance, ok, metrics, error))

    def save_stage(
        refresh_id: str,
        stage: str,
        duration_ms: int | None = None,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        stages.append((refresh_id, stage, duration_ms, extra))

    def publish_error(**kwargs: Any) -> None:
        errors.append(kwargs)

    recorder.save_stage = save_stage
    recorder.publish_error = publish_error
    pipeline = DisplayPipeline(
        display_manager=display_manager,
        housekeeper=housekeeper,
        recorder=recorder,
        update_plugin_health=update_health,
    )
    return pipeline, health_updates, stages, errors


def test_display_pipeline_success_records_metrics_and_stage(
    device_config_dev: Any,
) -> None:
    display_manager = _DisplayManager()
    pipeline, health_updates, stages, errors = _make_pipeline(
        device_config_dev, display_manager
    )
    action = ManualRefresh("clock", {})
    image = Image.new("RGB", device_config_dev.get_resolution(), "white")

    display_ms, preprocess_ms = pipeline.push_to_display(
        image=image,
        plugin_config={"image_settings": [{"name": "saturation", "value": 1}]},
        refresh_action=action,
        refresh_info=action.get_refresh_info(),
        benchmark_id="refresh-1",
        plugin_id="clock",
        instance_name=None,
        request_id="request-1",
    )

    assert (display_ms, preprocess_ms) == (21, 8)
    assert display_manager.calls[0]["history_meta"]["plugin_id"] == "clock"
    assert stages == [
        ("refresh-1", "display_pipeline", 21, None),
        ("refresh-1", "display_driver", 21, {"driver": "mock"}),
    ]
    assert health_updates == []
    assert errors == []


def test_display_pipeline_cached_path_releases_manual_waiter(
    device_config_dev: Any,
) -> None:
    display_manager = _DisplayManager()
    pipeline, _health_updates, stages, _errors = _make_pipeline(
        device_config_dev, display_manager
    )
    action = ManualRefresh("clock", {})
    request = ManualUpdateRequest("request-2", action)
    image = Image.new("RGB", device_config_dev.get_resolution(), "white")

    result = pipeline.push_or_skip_display(
        used_cached=True,
        image=image,
        plugin_config={},
        refresh_action=action,
        refresh_info=action.get_refresh_info(),
        benchmark_id="refresh-2",
        plugin_id="clock",
        instance_name=None,
        request_id="request-2",
        manual_request=request,
    )

    assert result == (None, None)
    assert request.image_saved.is_set()
    assert display_manager.calls == []
    assert stages == []


def test_display_pipeline_manual_callback_sets_image_saved_metrics(
    device_config_dev: Any,
) -> None:
    display_manager = _DisplayManager()
    pipeline, _health_updates, _stages, _errors = _make_pipeline(
        device_config_dev, display_manager
    )
    action = ManualRefresh("clock", {})
    request = ManualUpdateRequest("request-3", action)
    image = Image.new("RGB", device_config_dev.get_resolution(), "white")

    pipeline.push_to_display(
        image=image,
        plugin_config={},
        refresh_action=action,
        refresh_info=action.get_refresh_info(),
        benchmark_id="refresh-3",
        plugin_id="clock",
        instance_name=None,
        request_id="request-3",
        manual_request=request,
    )

    assert request.image_saved.is_set()
    assert request.image_saved_metrics == {
        "generate_ms": None,
        "preprocess_ms": 8,
        "display_ms": None,
        "stage": "image_saved",
    }


def test_display_pipeline_failure_records_health_and_progress_error(
    device_config_dev: Any, tmp_path: Any
) -> None:
    display_manager = _DisplayManager()
    display_manager.exception = RuntimeError("display offline")
    pipeline, health_updates, _stages, errors = _make_pipeline(
        device_config_dev, display_manager
    )
    action = ManualRefresh("clock", {})
    image = Image.new("RGB", device_config_dev.get_resolution(), "white")
    processed = tmp_path / "processed.png"
    processed.write_bytes(b"x")
    device_config_dev.processed_image_file = str(processed)

    with pytest.raises(RuntimeError, match="display offline"):
        pipeline.push_to_display(
            image=image,
            plugin_config={},
            refresh_action=action,
            refresh_info=action.get_refresh_info(),
            benchmark_id="refresh-4",
            plugin_id="clock",
            instance_name="Clock",
            request_id="request-4",
        )

    assert health_updates == [
        (
            "clock",
            "Clock",
            False,
            {"retained_display": True},
            "display offline",
        )
    ]
    assert errors == [
        {
            "plugin_id": "clock",
            "instance": "Clock",
            "refresh_id": "refresh-4",
            "request_id": "request-4",
            "error": "display offline",
            "retained_display": True,
        }
    ]

"""Plugin metadata belongs to one render, and plugins share one instance (A9).

Plugin instances are cached, so metadata a plugin set on one render (the
screenshot plugin's "Capture was blank") used to be reported again for every
later render that set none.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

import plugins.plugin_registry as registry
from plugins.base_plugin.base_plugin import BasePlugin
from refresh_task.actions import ManualRefresh, render_with_metadata
from refresh_task.executor import RefreshExecutor

NOW = datetime(2026, 11, 15, 8, 0, tzinfo=UTC)
CONFIG = SimpleNamespace(plugin_image_dir="/nonexistent")


class _BlankOnce(BasePlugin):
    """Reports a skipped capture on its first render only."""

    def __init__(self) -> None:
        super().__init__({"id": "blank_once"})
        self.renders = 0

    def generate_image(
        self, settings: Mapping[str, object], device_config: object
    ) -> Image.Image | None:
        self.renders += 1
        if self.renders == 1:
            self.set_latest_metadata({"skipped": True, "reason": "Capture was blank"})
        return Image.new("RGB", (4, 4), "white")


def test_a_render_that_sets_no_metadata_reports_none() -> None:
    plugin = _BlankOnce()
    action = ManualRefresh("blank_once", {})

    _, first = render_with_metadata(action, plugin, CONFIG, NOW)
    _, second = render_with_metadata(action, plugin, CONFIG, NOW)

    assert first == {"skipped": True, "reason": "Capture was blank"}
    assert second is None


def test_plugins_without_metadata_hooks_still_render() -> None:
    image = Image.new("RGB", (4, 4), "black")

    class _Bare:
        def generate_image(
            self, settings: Mapping[str, object], device_config: object
        ) -> Image.Image | None:
            return image

    result, meta = render_with_metadata(ManualRefresh("bare", {}), _Bare(), CONFIG, NOW)

    assert result is image
    assert meta is None


def test_inprocess_worker_reports_only_this_renders_metadata() -> None:
    plugin = _BlankOnce()
    owner = SimpleNamespace(_zombie_thread_count=0, _zombie_thread_lock=None)

    def run_once() -> dict[str, Any]:
        worker, holder, _ = RefreshExecutor.make_inprocess_worker_for(
            refresh_action=ManualRefresh("blank_once", {}),
            plugin_config={"id": "blank_once"},
            device_config=CONFIG,
            current_dt=NOW,
            plugin_id="blank_once",
            zombie_owner=owner,
            get_plugin_instance=lambda _config: plugin,
        )
        worker()
        return holder

    first = run_once()
    second = run_once()

    assert first["meta"] == {"skipped": True, "reason": "Capture was blank"}
    assert second["meta"] is None
    assert "error" not in second


def test_a_lazy_load_keeps_the_instance_another_thread_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner, loser = object(), object()

    def load_while_another_thread_wins(config: dict[str, Any]) -> object:
        # Another thread finishes its load first and caches its instance.
        registry.PLUGIN_CLASSES["race"] = winner
        return loser

    monkeypatch.setitem(registry._PLUGIN_CONFIGS, "race", {"id": "race"})
    monkeypatch.setattr(
        registry, "_load_single_plugin_instance", load_while_another_thread_wins
    )
    try:
        assert registry.get_plugin_instance({"id": "race"}) is winner
        assert registry.get_plugin_instance({"id": "race"}) is winner
    finally:
        registry.PLUGIN_CLASSES.pop("race", None)

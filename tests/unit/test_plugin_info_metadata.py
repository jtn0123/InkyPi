"""``plugin-info.json`` carries what the main process needs to know (A6).

The refresh loop runs in the main process and plugins render in a worker. Two
things the loop needs per turn, the progress label for API-key plugins and
whether to ask the optional skip hook, come from the metadata, so the main
process doesn't load plugin code. These tests keep the metadata honest.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from plugins.base_plugin.base_plugin import BasePlugin
from refresh_task.plugin_lookup import _plugin_requires_api_key

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_DIR = REPO_ROOT / "src" / "plugins"
SCHEMA_PATH = REPO_ROOT / "src" / "config" / "schemas" / "plugin-info.schema.json"


def _plugin_infos() -> list[dict[str, Any]]:
    infos = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(PLUGINS_DIR.glob("*/plugin-info.json"))
    ]
    assert len(infos) >= 10, "expected the built-in plugins"
    return infos


def _ids(infos: list[dict[str, Any]]) -> list[str]:
    return [str(info["id"]) for info in infos]


INFOS = _plugin_infos()


def _plugin_class(info: Mapping[str, Any]) -> type[BasePlugin]:
    module = importlib.import_module(f"plugins.{info['id']}.{info['id']}")
    cls: type[BasePlugin] = getattr(module, str(info["class"]))
    assert issubclass(cls, BasePlugin)
    return cls


@pytest.mark.parametrize("info", INFOS, ids=_ids(INFOS))
def test_plugin_info_matches_the_schema(info: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(info, schema)


@pytest.mark.parametrize("info", INFOS, ids=_ids(INFOS))
def test_requires_api_key_matches_the_settings_form(info: dict[str, Any]) -> None:
    plugin = _plugin_class(info)(dict(info))
    template = plugin.generate_settings_template()

    assert ("api_key" in template) is (info.get("requires_api_key") is True), (
        f"{info['id']}: set requires_api_key in plugin-info.json exactly when "
        "the settings form asks for an API key"
    )


@pytest.mark.parametrize("info", INFOS, ids=_ids(INFOS))
def test_skip_flag_matches_the_hook(info: dict[str, Any]) -> None:
    cls = _plugin_class(info)
    overrides = cls.skip_display_condition is not BasePlugin.skip_display_condition

    assert overrides is (info.get("skip_display_condition") is True), (
        f"{info['id']}: set skip_display_condition in plugin-info.json exactly "
        "when the class implements the hook, or the scheduler won't ask it"
    )


def _refuse_to_load(_cfg: Any) -> Any:
    raise AssertionError("the main process loaded plugin code")


def test_api_key_label_reads_metadata_without_loading_the_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "refresh_task.plugin_lookup.get_plugin_instance", _refuse_to_load
    )

    assert _plugin_requires_api_key({"id": "weather", "requires_api_key": True})
    assert not _plugin_requires_api_key({"id": "clock"})
    assert not _plugin_requires_api_key({"id": "x", "requires_api_key": "yes"})


def test_unflagged_plugins_are_not_loaded_to_ask_the_skip_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from refresh_task.actions import PlaylistRefresh
    from refresh_task.task import RefreshTask

    monkeypatch.setattr(
        "refresh_task.plugin_lookup.get_plugin_instance", _refuse_to_load
    )
    device_config = MagicMock()
    device_config.get_config.return_value = 3600
    task = RefreshTask(device_config, MagicMock())
    playlist = MagicMock()
    instance = MagicMock()
    instance.settings = {}

    reason = task._skip_display_reason(
        PlaylistRefresh(playlist, instance), {"id": "clock"}, datetime.now(UTC)
    )

    assert reason is None

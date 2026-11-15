"""The code in docs/building_plugins.md runs against the current plugin API."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "building_plugins.md"


def _blocks(language: str, text: str) -> list[str]:
    return re.findall(rf"```{language}\n(.*?)```", text, re.DOTALL)


def _hello_world() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    return text[text.index("## Hello World walkthrough") :]


def test_every_json_example_is_valid_json() -> None:
    blocks = _blocks("json", GUIDE.read_text(encoding="utf-8"))
    assert blocks
    for block in blocks:
        json.loads(block)


def test_hello_world_plugin_works(device_config_dev: Any) -> None:
    info = json.loads(_blocks("json", _hello_world())[0])
    namespace: dict[str, Any] = {}
    exec(compile(_blocks("python", _hello_world())[0], "hello.py", "exec"), namespace)
    plugin = namespace[info["class"]]({"id": info["id"]})

    from utils.form_utils import validate_plugin_required_fields

    section = plugin.build_settings_schema()["sections"][0]
    assert [item["name"] for item in section["items"]] == ["message"]
    assert validate_plugin_required_fields(plugin, {"message": ""})
    assert plugin.validate_settings({"message": "x" * 61})
    assert plugin.validate_settings({"message": "Hello"}) is None

    image = plugin.generate_image({"message": "Hello"}, device_config_dev)
    assert isinstance(image, Image.Image)
    assert image.size == plugin.get_oriented_dimensions(device_config_dev)


def test_schema_example_builds() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    start = text.index("### 3. Describe the Settings Form")
    example = _blocks("python", text[start:])[0]
    namespace: dict[str, Any] = {}
    exec(
        compile(
            "from plugins.base_plugin.base_plugin import BasePlugin\n" + example,
            "countdown_example.py",
            "exec",
        ),
        namespace,
    )
    schema = namespace["Countdown"]({"id": "countdown"}).build_settings_schema()
    assert schema["sections"][0]["title"] == "Countdown"

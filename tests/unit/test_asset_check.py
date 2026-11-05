# pyright: reportMissingImports=false
"""Tests for the boot-time asset manifest check (B10)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from utils.app_utils import FONT_FAMILIES
from utils.asset_check import check_assets, run_boot_check


def _build_tree(root: Path, *, with_dist: bool = True) -> Path:
    """Create a minimal but complete src/ tree under *root*."""
    for variants in FONT_FAMILIES.values():
        for variant in variants:
            path = root / "static" / "fonts" / variant["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"font")

    scripts = root / "static" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "theme.js").write_text("//")
    (scripts / "common_manifest.json").write_text(
        json.dumps([{"path": "theme.js", "defer": False}])
    )
    styles = root / "static" / "styles"
    styles.mkdir(parents=True)
    (styles / "main.css").write_text("/* */")

    if with_dist:
        dist = root / "static" / "dist"
        dist.mkdir(parents=True)
        (dist / "common.abc.min.js").write_text("//")
        (dist / "common.abc.min.css").write_text("/* */")
        (dist / "manifest.json").write_text(
            json.dumps(
                {"common.js": "common.abc.min.js", "common.css": "common.abc.min.css"}
            )
        )

    base_render = root / "plugins" / "base_plugin" / "render"
    base_render.mkdir(parents=True)
    (base_render / "plugin.html").write_text("<html>")

    weather = root / "plugins" / "weather"
    (weather / "render").mkdir(parents=True)
    (weather / "icon.png").write_bytes(b"png")
    (weather / "render" / "weather.html").write_text("<html>")
    (weather / "render" / "weather.css").write_text("/* */")
    (weather / "weather.py").write_text(
        "class Weather:\n"
        "    def generate_image(self, settings, device_config):\n"
        "        return self.render_image(\n"
        '            dimensions, "weather.html", "weather.css", template_params\n'
        "        )\n"
    )
    return root


def test_complete_tree_reports_ok(tmp_path: Path) -> None:
    root = _build_tree(tmp_path)
    report = check_assets(["weather"], src_root=root)
    assert report["ok"] is True
    assert report["missing"] == []
    assert report["degraded"] == []
    assert report["missing_count"] == 0
    assert report["checked"] > len(FONT_FAMILIES)


def test_missing_font_icon_template_and_css_are_listed(tmp_path: Path) -> None:
    root = _build_tree(tmp_path)
    (root / "static" / "fonts" / "Jost.ttf").unlink()
    (root / "plugins" / "weather" / "icon.png").unlink()
    (root / "plugins" / "weather" / "render" / "weather.html").unlink()
    (root / "plugins" / "weather" / "render" / "weather.css").unlink()

    report = check_assets(["weather"], src_root=root)

    assert report["ok"] is False
    assert set(report["missing"]) == {
        "static/fonts/Jost.ttf",
        "plugins/weather/icon.png",
        "plugins/weather/render/weather.html",
        "plugins/weather/render/weather.css",
    }
    assert report["missing_count"] == 4


def test_template_found_in_base_plugin_render_dir(tmp_path: Path) -> None:
    root = _build_tree(tmp_path)
    plugin = root / "plugins" / "weather"
    (plugin / "weather.py").write_text(
        'x = self.render_image(dimensions, "plugin.html")\n'
    )
    report = check_assets(["weather"], src_root=root)
    assert report["ok"] is True


def test_unknown_plugin_directory_is_missing(tmp_path: Path) -> None:
    root = _build_tree(tmp_path)
    report = check_assets(["ghost"], src_root=root)
    assert report["missing"] == ["plugins/ghost/ (plugin directory)"]


def test_missing_dist_manifest_is_degraded_not_missing(tmp_path: Path) -> None:
    root = _build_tree(tmp_path, with_dist=False)
    report = check_assets([], src_root=root)
    assert report["ok"] is True
    assert len(report["degraded"]) == 1
    assert "static/dist/manifest.json" in report["degraded"][0]


def test_dist_manifest_pointing_at_missing_bundle_is_missing(tmp_path: Path) -> None:
    root = _build_tree(tmp_path)
    (root / "static" / "dist" / "common.abc.min.js").unlink()
    report = check_assets([], src_root=root)
    assert report["missing"] == ["static/dist/common.abc.min.js"]


def test_unbundled_script_fallback_is_checked(tmp_path: Path) -> None:
    root = _build_tree(tmp_path)
    (root / "static" / "scripts" / "theme.js").unlink()
    (root / "static" / "styles" / "main.css").unlink()
    report = check_assets([], src_root=root)
    assert set(report["missing"]) == {
        "static/scripts/theme.js",
        "static/styles/main.css",
    }


def test_missing_list_is_capped(tmp_path: Path) -> None:
    root = _build_tree(tmp_path)
    report = check_assets([f"ghost{i}" for i in range(80)], src_root=root)
    assert len(report["missing"]) == 50
    assert report["missing_count"] == 80


def test_real_source_tree_has_no_missing_assets() -> None:
    """The shipped plugins, fonts and scripts must all be present."""
    src = Path(__file__).resolve().parents[2] / "src"
    plugin_ids = [
        p.name
        for p in (src / "plugins").iterdir()
        if (p / "plugin-info.json").is_file()
    ]
    report = check_assets(plugin_ids)
    assert report["missing"] == []


def test_run_boot_check_warns_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import utils.asset_check as mod

    root = _build_tree(tmp_path)
    (root / "plugins" / "weather" / "icon.png").unlink()
    monkeypatch.setattr(mod, "_SRC_ROOT", root)

    with caplog.at_level(logging.INFO, logger="utils.asset_check"):
        report = run_boot_check(["weather"])

    assert report["ok"] is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings and "plugins/weather/icon.png" in warnings[0].getMessage()


def test_run_boot_check_never_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import utils.asset_check as mod

    def _boom(*_a: object, **_k: object) -> dict[str, object]:
        raise OSError("disk gone")

    monkeypatch.setattr(mod, "check_assets", _boom)
    report = run_boot_check(["weather"])
    assert report["ok"] is None
    assert report["error"] == "asset check failed to run"

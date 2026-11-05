"""Boot-time asset manifest check (B10).

The app degrades quietly when a file it needs is gone: a missing font makes
``get_font`` raise mid-render, a missing plugin icon is a broken ``<img>``, a
missing render template fails the plugin's first refresh, and a missing
``static/dist`` bundle silently drops the UI back to individual script tags.
None of that is *reported* anywhere, so the first symptom is a plugin getting
blamed for a broken install.

:func:`check_assets` ``stat()``\\ s every asset the app is known to need once at
boot and returns a small report that ``/api/diagnostics`` surfaces. It must
stay cheap: existence checks only — no rendering, no parsing beyond the two
small JSON manifests and a regex over plugin sources for template names.

Two severities:

* ``missing`` — something will visibly break (a font, icon, template, or a
  file the bundle manifest promises).
* ``degraded`` — the app has a designed fallback (no ``static/dist`` bundle:
  pages serve the unbundled scripts instead), so it is worth knowing about
  but not a fault. Dev checkouts that never ran ``build_assets.py`` land here.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SRC_ROOT = Path(__file__).resolve().parents[1]

#: ``self.render_image(dimensions, "x.html", "x.css", ...)`` and the module-level
#: helper form ``plugin_instance.render_image(dimensions, "x.html", "x.css")``.
_RENDER_CALL_RE = re.compile(
    r"render_image\(\s*[\w.]+\s*,\s*[\"']([^\"']+\.html)[\"']"
    r"(?:\s*,\s*[\"']([^\"']+\.css)[\"'])?"
)

#: Bundles ``setup_asset_helpers`` requires before it enables bundling.
_REQUIRED_BUNDLES = ("common.js", "common.css")

#: Keep the payload bounded even if an install is badly broken.
_MAX_REPORTED = 50


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _font_files() -> list[str]:
    from utils.app_utils import FONT_FAMILIES

    return [
        str(Path("static") / "fonts" / variant["file"])
        for variants in FONT_FAMILIES.values()
        for variant in variants
    ]


def _plugin_template_refs(plugin_dir: Path) -> set[tuple[str, str | None]]:
    """Return ``(html, css)`` pairs a plugin's sources pass to ``render_image``."""
    refs: set[tuple[str, str | None]] = set()
    for source in plugin_dir.glob("*.py"):
        try:
            text = source.read_text(encoding="utf-8")
        except OSError:
            continue
        for html, css in _RENDER_CALL_RE.findall(text):
            refs.add((html, css or None))
    return refs


def _check_plugin(plugin_id: str, src_root: Path) -> tuple[list[str], int]:
    """Return ``(missing, checked)`` for one plugin's icon and templates."""
    plugin_dir = src_root / "plugins" / plugin_id
    if not plugin_dir.is_dir():
        return [f"plugins/{plugin_id}/ (plugin directory)"], 1

    missing: list[str] = []
    checked = 1
    icon = plugin_dir / "icon.png"
    checked += 1
    if not icon.is_file():
        missing.append(_rel(icon, src_root))

    render_dir = plugin_dir / "render"
    base_render = src_root / "plugins" / "base_plugin" / "render"
    for html, css in sorted(_plugin_template_refs(plugin_dir), key=str):
        checked += 1
        # BasePlugin searches the plugin's own render dir first, then the base.
        if not any((d / html).is_file() for d in (render_dir, base_render)):
            missing.append(_rel(render_dir / html, src_root))
        if css is not None:
            checked += 1
            if not (render_dir / css).is_file():
                missing.append(_rel(render_dir / css, src_root))
    return missing, checked


def _check_bundles(src_root: Path) -> tuple[list[str], list[str], int]:
    """Check ``static/dist/manifest.json`` and the unbundled script fallback."""
    missing: list[str] = []
    degraded: list[str] = []
    checked = 0

    scripts_dir = src_root / "static" / "scripts"
    common_manifest = scripts_dir / "common_manifest.json"
    checked += 1
    # setup_asset_helpers reads this unguarded, so it is a hard requirement.
    try:
        sources = json.loads(common_manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        missing.append(_rel(common_manifest, src_root))
        sources = []
    for entry in sources if isinstance(sources, list) else []:
        name = entry.get("path") if isinstance(entry, dict) else None
        if isinstance(name, str) and name:
            checked += 1
            if not (scripts_dir / name).is_file():
                missing.append(_rel(scripts_dir / name, src_root))

    main_css = src_root / "static" / "styles" / "main.css"
    checked += 1
    if not main_css.is_file():
        missing.append(_rel(main_css, src_root))

    dist = src_root / "static" / "dist"
    manifest_path = dist / "manifest.json"
    checked += 1
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        degraded.append(
            f"{_rel(manifest_path, src_root)} (bundling disabled; "
            "serving unbundled scripts)"
        )
        return missing, degraded, checked
    except (OSError, ValueError):
        missing.append(f"{_rel(manifest_path, src_root)} (unreadable)")
        return missing, degraded, checked

    if not isinstance(manifest, dict):
        missing.append(f"{_rel(manifest_path, src_root)} (not an object)")
        return missing, degraded, checked
    for logical in _REQUIRED_BUNDLES:
        checked += 1
        target = manifest.get(logical)
        if not isinstance(target, str) or not target:
            missing.append(f"{_rel(manifest_path, src_root)}: {logical} entry")
            continue
        path = dist / Path(target).name
        if not path.is_file():
            missing.append(_rel(path, src_root))
    return missing, degraded, checked


def check_assets(
    plugin_ids: Iterable[str], src_root: Path | None = None
) -> dict[str, Any]:
    """Stat every required asset and return a diagnostics report.

    Args:
        plugin_ids: Plugins the device has configured; each is checked for its
            icon and the render templates its sources reference.
        src_root: Override for the ``src`` directory (tests).

    Returns:
        ``{"ok", "checked", "missing", "degraded", "checked_at"}``. ``ok`` is
        False only when something in ``missing`` would visibly break.
    """
    root = src_root or _SRC_ROOT
    missing: list[str] = []
    checked = 0

    for font in _font_files():
        checked += 1
        if not (root / font).is_file():
            missing.append(font)

    for plugin_id in sorted(set(plugin_ids)):
        plugin_missing, plugin_checked = _check_plugin(plugin_id, root)
        missing.extend(plugin_missing)
        checked += plugin_checked

    bundle_missing, degraded, bundle_checked = _check_bundles(root)
    missing.extend(bundle_missing)
    checked += bundle_checked

    return {
        "ok": not missing,
        "checked": checked,
        "missing": missing[:_MAX_REPORTED],
        "missing_count": len(missing),
        "degraded": degraded,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def run_boot_check(plugin_ids: Iterable[str]) -> dict[str, Any]:
    """Run :func:`check_assets` and log the outcome.

    Never raises: a broken checker must not stop the app from starting.
    """
    try:
        report = check_assets(plugin_ids)
    except Exception:  # noqa: BLE001 — boot must not fail on a diagnostic
        logger.warning("Asset manifest check failed to run", exc_info=True)
        report = {
            "ok": None,
            "checked": 0,
            "missing": [],
            "missing_count": 0,
            "degraded": [],
            "checked_at": datetime.now(UTC).isoformat(),
            "error": "asset check failed to run",
        }
    if report["missing"]:
        logger.warning(
            "Asset check: %d missing asset(s): %s",
            report["missing_count"],
            ", ".join(report["missing"]),
        )
    elif report["degraded"]:
        logger.info("Asset check: degraded: %s", ", ".join(report["degraded"]))
    else:
        logger.info("Asset check: all %d assets present", report["checked"])
    return report

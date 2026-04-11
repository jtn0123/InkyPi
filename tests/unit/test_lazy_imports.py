"""Regression tests for lazy-import discipline on the startup path (JTN-606).

These are *structural* assertions, not numeric byte budgets: they verify
that certain heavy modules are NOT pulled into ``sys.modules`` when
``inkypi`` (or selected startup-path dependencies) are imported fresh in
a subprocess.

The goal is to prevent regressions where a well-meaning refactor reintroduces
a module-level ``from playwright import ...`` or ``from PIL import ImageDraw``
on one of the eager import paths, silently inflating startup RSS on
low-memory devices like the Pi Zero 2 W.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"

# Modules that must NOT be loaded when the server starts up.  Each entry is
# the dotted name as it appears in ``sys.modules`` after a successful
# ``import inkypi``.  Anything listed here is only required by a specific
# render path / plugin and can be deferred to first use.
FORBIDDEN_STARTUP_MODULES = (
    # Playwright is only used by the screenshot render path.
    "playwright",
    "playwright.sync_api",
    # Heavy PIL submodules — ImageDraw/Font/Filter/Enhance/Ops are only
    # needed once an image is actually rendered or enhanced.
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageFilter",
    "PIL.ImageEnhance",
    "PIL.ImageOps",
    # pi_heif's native extension is ~3 MB RSS + ~28 ms import time and is
    # only needed when a HEIF/HEIC file is actually decoded.
    "pi_heif",
    # ``requests`` / ``urllib3`` pull charset_normalizer/chardet and bring
    # in ~8 MB RSS.  They are only used when an HTTP call is actually made.
    "requests",
    "urllib3",
    "charset_normalizer",
    "chardet",
    # AI SDKs are only used by the ai_image / ai_text plugins (lazy loaded
    # via the plugin registry), so they must not appear at startup.
    "openai",
    "anthropic",
)


def _run_fresh_python(code: str) -> dict[str, object]:
    """Run *code* in a fresh Python subprocess and return the decoded JSON result.

    The subprocess has ``src`` on ``PYTHONPATH`` and runs with minimal env so
    plugin registration does not depend on host device state.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    env["INKYPI_ENV"] = "dev"
    env["INKYPI_NO_REFRESH"] = "1"
    # Keep test output small — suppress noisy warnings from the inky library.
    env["PYTHONWARNINGS"] = "ignore"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            "Startup probe subprocess failed.\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _probe(target_import: str) -> dict[str, object]:
    code = textwrap.dedent(f"""
        import json, sys
        {target_import}
        print(json.dumps({{
            "modules": sorted(sys.modules.keys()),
            "count": len(sys.modules),
        }}))
        """)
    return _run_fresh_python(code)


@pytest.mark.parametrize("forbidden", FORBIDDEN_STARTUP_MODULES)
def test_inkypi_startup_does_not_import_heavy_module(forbidden: str) -> None:
    """``import inkypi`` must not transitively load *forbidden*.

    Each heavy module is checked individually so a failure clearly names
    which dependency leaked back onto the startup path.
    """
    result = _probe("import inkypi")
    loaded = set(result["modules"])  # type: ignore[arg-type]
    assert forbidden not in loaded, (
        f"{forbidden!r} was imported during inkypi startup. "
        "Something on the critical path (inkypi.py, app_setup.*, "
        "utils.app_utils, utils.http_utils, utils.webhooks, utils.fallback_image, "
        "utils.image_utils, refresh_task, plugins.plugin_registry) "
        "now pulls it in eagerly. Move the import into the function that "
        "actually uses it (see JTN-606)."
    )


def test_inkypi_startup_module_count_is_bounded() -> None:
    """Sanity bound on the number of modules loaded by ``import inkypi``.

    The exact number drifts with dependency updates, so we only assert an
    upper bound generous enough to avoid flakes while still catching a
    regression that reintroduces a major dep tree (e.g. pandas).
    """
    result = _probe("import inkypi")
    count = int(result["count"])  # type: ignore[arg-type]
    # As of JTN-606 the count is ~545 locally.  Leave comfortable slack so
    # upstream dependency changes do not break this, but fail loudly if a
    # ~100-module package (numpy/pandas/playwright) silently gets added.
    assert count < 750, (
        f"inkypi startup now loads {count} modules. "
        "A heavy dependency may have been accidentally added to the "
        "startup path. Profile with 'python -X importtime -c \"import inkypi\"' "
        "to find the culprit. See JTN-606 for the lazy-import policy."
    )


def test_http_utils_helpers_do_not_require_requests_at_import_time() -> None:
    """``from utils.http_utils import json_error`` must not load ``requests``.

    The json_* helpers are pure Flask wrappers used by every error handler
    on the startup path. Keeping ``requests`` out of that import chain is a
    core piece of the JTN-606 memory reduction.
    """
    result = _probe("from utils.http_utils import json_error, json_success, wants_json")
    loaded = set(result["modules"])  # type: ignore[arg-type]
    assert "requests" not in loaded
    assert "urllib3" not in loaded


def test_fallback_image_import_does_not_load_pil_draw() -> None:
    """Importing the fallback image module must not drag in ``PIL.ImageDraw``.

    ``render_error_image`` is only called when a plugin refresh raises, so
    ``PIL.ImageDraw`` should only be loaded on the first failure — never
    during normal startup.
    """
    result = _probe("import utils.fallback_image")
    loaded = set(result["modules"])  # type: ignore[arg-type]
    assert "PIL.ImageDraw" not in loaded

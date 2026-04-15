# pyright: reportMissingImports=false
"""Structural validation of scripts/dev_watch.sh and its dispatcher helper.

The filesystem watcher itself is not exercised here (it's flaky in CI and
depends on inotify/FSEvents). Instead we validate that:

* The shell script has a shebang, is executable, and invokes watchmedo with
  the expected watched directories and patterns.
* The Python dispatcher routes by directory, debounces rapid events within a
  200 ms window, and emits the documented log line format.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
WATCH_SH = SCRIPTS_DIR / "dev_watch.sh"
DISPATCH_PY = SCRIPTS_DIR / "_dev_watch_dispatch.py"


# ---------------------------------------------------------------------------
# Shell script structure
# ---------------------------------------------------------------------------


class TestDevWatchShellScript:
    @pytest.fixture(autouse=True)
    def _load(self):
        assert WATCH_SH.is_file(), f"missing {WATCH_SH}"
        self.content = WATCH_SH.read_text()

    def test_has_bash_shebang(self):
        first_line = self.content.splitlines()[0]
        assert first_line.startswith("#!"), "script must start with a shebang"
        assert "bash" in first_line

    def test_is_executable(self):
        mode = WATCH_SH.stat().st_mode
        assert mode & 0o111, "dev_watch.sh must be chmod +x"

    def test_uses_strict_mode(self):
        assert "set -euo pipefail" in self.content

    def test_invokes_watchmedo(self):
        # Either the CLI shim or the python -m fallback counts.
        assert "watchmedo" in self.content or "watchdog.watchmedo" in self.content

    def test_watches_expected_directories(self):
        for needle in (
            "src/static/styles",
            "src/static/scripts",
            "src/templates",
        ):
            assert needle in self.content, f"script must watch {needle}"

    def test_recursive_watch(self):
        assert "--recursive" in self.content

    def test_patterns_cover_css_js_html(self):
        match = re.search(r'--patterns=["\']([^"\']+)["\']', self.content)
        assert match, "expected --patterns=... in watchmedo invocation"
        patterns = match.group(1)
        for ext in ("*.css", "*.js", "*.html"):
            assert ext in patterns

    def test_ignores_generated_outputs(self):
        # Prevent rebuild loops from main.css and dist/ bundle writes.
        assert "--ignore-patterns" in self.content
        assert "main.css" in self.content
        assert "dist" in self.content

    def test_checks_watchdog_installed(self):
        assert "import watchdog" in self.content
        # Must print an install hint when missing.
        assert "pip install watchdog" in self.content

    def test_handles_ctrl_c_cleanly(self):
        # A trap on INT/TERM ensures the last line is our message, not a
        # Python KeyboardInterrupt traceback.
        assert "trap" in self.content
        assert "INT" in self.content

    def test_uses_venv_python_when_present(self):
        assert ".venv/bin/python" in self.content


# ---------------------------------------------------------------------------
# Dispatcher helper
# ---------------------------------------------------------------------------


class TestDispatcherStructure:
    @pytest.fixture(autouse=True)
    def _load(self):
        assert DISPATCH_PY.is_file(), f"missing {DISPATCH_PY}"
        self.content = DISPATCH_PY.read_text()

    def test_has_python_shebang(self):
        first_line = self.content.splitlines()[0]
        assert first_line.startswith("#!"), "must start with shebang"
        assert "python" in first_line

    def test_is_executable(self):
        mode = DISPATCH_PY.stat().st_mode
        assert mode & 0o111, "_dev_watch_dispatch.py must be chmod +x"

    def test_defines_200ms_debounce(self):
        assert "DEBOUNCE_SECONDS = 0.2" in self.content

    def test_routes_all_three_kinds(self):
        for kind in ("css", "js", "template"):
            assert f'"{kind}"' in self.content or f"'{kind}'" in self.content

    def test_log_format_matches_spec(self):
        # Required format: "[<iso-timestamp>] <action> (source: <name>)"
        assert "rebuild css" in self.content
        assert "rebuild js" in self.content
        assert "(source:" in self.content


# ---------------------------------------------------------------------------
# Dispatcher behavior — import and exercise pure-python pieces in isolation.
# No filesystem watcher is started; we just call helpers directly.
# ---------------------------------------------------------------------------


@pytest.fixture
def dispatch_module(monkeypatch, tmp_path):
    """Import the dispatcher with a temp state dir so debounce is hermetic."""
    # Load the module by path (it lives outside any package).
    import importlib.util

    spec = importlib.util.spec_from_file_location("dev_watch_dispatch", DISPATCH_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Redirect the on-disk debounce state into tmp.
    monkeypatch.setattr(mod, "_STATE_DIR", tmp_path / "state")
    return mod


class TestDispatcherBehavior:
    def test_kind_for_routes_by_directory(self, dispatch_module):
        mod = dispatch_module
        styles_file = REPO_ROOT / "src" / "static" / "styles" / "main.css"
        scripts_file = REPO_ROOT / "src" / "static" / "scripts" / "csrf.js"
        tmpl_file = REPO_ROOT / "src" / "templates" / "base.html"
        outside = REPO_ROOT / "README.md"

        assert mod._kind_for(styles_file) == "css"
        assert mod._kind_for(scripts_file) == "js"
        assert mod._kind_for(tmpl_file) == "template"
        assert mod._kind_for(outside) is None

    def test_debounce_blocks_rapid_second_call(self, dispatch_module):
        mod = dispatch_module
        assert mod._debounce("css") is True
        # Immediately after: within 200ms window, should block.
        assert mod._debounce("css") is False

    def test_debounce_clears_after_window(self, dispatch_module, monkeypatch):
        mod = dispatch_module
        # Pretend time jumped forward past the debounce window.
        real_monotonic = time.monotonic
        base = real_monotonic()
        seq = iter([base, base + 1.0])
        monkeypatch.setattr(mod.time, "monotonic", lambda: next(seq))
        assert mod._debounce("js") is True
        assert mod._debounce("js") is True

    def test_log_format(self, dispatch_module, capsys):
        mod = dispatch_module
        mod._log("rebuild css", Path("_buttons.css"))
        out = capsys.readouterr().out.strip()
        assert re.match(
            r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\] rebuild css "
            r"\(source: _buttons\.css\)$",
            out,
        ), f"unexpected log line: {out!r}"


# ---------------------------------------------------------------------------
# Requirements entry
# ---------------------------------------------------------------------------


class TestWatchdogDependencyDeclared:
    def test_watchdog_in_requirements_dev_in(self):
        req_in = (REPO_ROOT / "install" / "requirements-dev.in").read_text()
        # Tolerate any version constraint — we just want it present.
        assert re.search(r"^watchdog[>=<~!\s]", req_in, re.MULTILINE), (
            "watchdog should be declared in install/requirements-dev.in "
            "so contributors know it's an expected dev dependency"
        )

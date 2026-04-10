# pyright: reportMissingImports=false
"""Tests for cysystemd notify() fix — JTN-594.

Ensures both inkypi.py and task.py use the Notification enum API (not raw
strings) when calling cysystemd notify(). Regression tests to catch anyone
re-introducing the string-based call that caused the systemd restart loop.
"""

import ast
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text()


def _ast_tree(rel_path: str) -> ast.Module:
    return ast.parse(_source(rel_path))


def _find_call_nodes(tree: ast.Module, func_name: str) -> list[ast.Call]:
    """Return every ast.Call whose func is a Name or Attribute matching func_name."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == func_name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == func_name)
        )
    ]


def _imports_name(tree: ast.Module, module: str, name: str) -> bool:
    """Return True if the tree contains 'from <module> import <name> ...'."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                if alias.name == name:
                    return True
    return False


# ---------------------------------------------------------------------------
# Structural tests (AST-level) — catch regression without running the code
# ---------------------------------------------------------------------------


class TestInkypiStructural:
    """Verify inkypi.py imports and uses the Notification enum for sd_notify."""

    def setup_method(self):
        self.tree = _ast_tree("src/inkypi.py")

    def test_imports_notification_enum(self):
        """inkypi.py must import Notification from cysystemd.daemon."""
        assert _imports_name(self.tree, "cysystemd.daemon", "Notification"), (
            "inkypi.py does not import Notification from cysystemd.daemon — "
            "the string-based notify() bug (JTN-594) may have been reintroduced."
        )

    def test_imports_notify(self):
        """inkypi.py must import notify from cysystemd.daemon."""
        assert _imports_name(
            self.tree, "cysystemd.daemon", "notify"
        ), "inkypi.py does not import notify from cysystemd.daemon."

    def test_no_string_ready_arg_to_notify(self):
        """notify() must never be called with a bare string literal 'READY=1'."""
        tree = self.tree
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value == "READY=1":
                        pytest.fail(
                            "notify() is called with a string literal 'READY=1' in inkypi.py. "
                            "Use notify(Notification.READY) instead (JTN-594)."
                        )


class TestTaskStructural:
    """Verify task.py imports Notification and uses the enum-based adapter."""

    def setup_method(self):
        self.tree = _ast_tree("src/refresh_task/task.py")

    def test_imports_notification_enum(self):
        """task.py must import Notification (as _sd_Notification) from cysystemd.daemon."""
        assert _imports_name(self.tree, "cysystemd.daemon", "Notification"), (
            "task.py does not import Notification from cysystemd.daemon — "
            "the string-based notify() bug (JTN-594) may have been reintroduced."
        )

    def test_no_raw_string_watchdog_call(self):
        """_sd_notify_raw must never be called directly with a string literal."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in (
                        "WATCHDOG=1",
                        "READY=1",
                    ):
                        # Only flag if the call is _sd_notify_raw (not the adapter function itself)
                        func = node.func
                        if isinstance(func, ast.Name) and func.id == "_sd_notify_raw":
                            pytest.fail(
                                f"_sd_notify_raw() called with string '{arg.value}' in task.py. "
                                "Use _sd_Notification.<VARIANT> instead (JTN-594)."
                            )

    def test_except_blocks_do_not_bare_pass(self):
        """No except block in the cysystemd import try/except should be a bare pass."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Try):
                is_cysystemd_try = any(
                    isinstance(stmt, ast.ImportFrom)
                    and stmt.module == "cysystemd.daemon"
                    for stmt in node.body
                )
                if is_cysystemd_try:
                    for handler in node.handlers:
                        if len(handler.body) == 1 and isinstance(
                            handler.body[0], ast.Pass
                        ):
                            pytest.fail(
                                "cysystemd import try/except in task.py uses bare 'pass'. "
                                "This silently swallows errors. Use logger.exception() or set _sd_notify = None explicitly."
                            )


# ---------------------------------------------------------------------------
# Behavioural / mock-based tests — verify the adapter dispatches correctly
# ---------------------------------------------------------------------------


class TestSdNotifyAdapter:
    """Test the _sd_notify adapter function in task.py calls the enum API."""

    def _load_task_module_with_mock_cysystemd(self):
        """Import task.py with cysystemd mocked so the adapter is defined."""
        # Build a fake cysystemd.daemon module with a real-looking Notification enum
        import enum

        class FakeNotification(enum.Enum):
            READY = "READY=1"
            WATCHDOG = "WATCHDOG=1"
            STOPPING = "STOPPING=1"

        fake_notify = MagicMock()

        fake_daemon = types.ModuleType("cysystemd.daemon")
        fake_daemon.notify = fake_notify
        fake_daemon.Notification = FakeNotification

        fake_cysystemd = types.ModuleType("cysystemd")
        fake_cysystemd.daemon = fake_daemon

        # Patch sys.modules so the import inside task.py picks up our fakes
        patched_modules = {
            "cysystemd": fake_cysystemd,
            "cysystemd.daemon": fake_daemon,
        }

        # Also stub heavy dependencies so task.py can be fully imported
        for mod_name in [
            "waveshare_epd",
            "gpiozero",
            "PIL",
            "PIL.Image",
            "PIL.ImageDraw",
            "PIL.ImageFont",
        ]:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = types.ModuleType(mod_name)

        task_module_name = "refresh_task_jtn594_test"
        if task_module_name in sys.modules:
            del sys.modules[task_module_name]

        # We import as a spec from the actual file path
        spec = importlib.util.spec_from_file_location(
            task_module_name,
            SRC_DIR / "refresh_task" / "task.py",
        )
        module = importlib.util.module_from_spec(spec)
        module.__spec__ = spec

        with patch.dict(sys.modules, patched_modules):
            # Re-add src to path if needed
            if str(SRC_DIR) not in sys.path:
                sys.path.insert(0, str(SRC_DIR))
            spec.loader.exec_module(module)

        return module, fake_notify, FakeNotification

    def test_watchdog_calls_notification_watchdog(self):
        """_sd_notify('WATCHDOG=1') must call notify(Notification.WATCHDOG)."""
        module, fake_notify, FakeNotification = (
            self._load_task_module_with_mock_cysystemd()
        )
        assert (
            module._sd_notify is not None
        ), "_sd_notify should be defined when cysystemd is available"
        module._sd_notify("WATCHDOG=1")
        fake_notify.assert_called_once_with(FakeNotification.WATCHDOG)

    def test_ready_calls_notification_ready(self):
        """_sd_notify('READY=1') must call notify(Notification.READY)."""
        module, fake_notify, FakeNotification = (
            self._load_task_module_with_mock_cysystemd()
        )
        assert (
            module._sd_notify is not None
        ), "_sd_notify should be defined when cysystemd is available"
        module._sd_notify("READY=1")
        fake_notify.assert_called_once_with(FakeNotification.READY)

    def test_unknown_kind_does_not_call_raw(self):
        """Unknown _kind strings must not trigger any notify call."""
        module, fake_notify, FakeNotification = (
            self._load_task_module_with_mock_cysystemd()
        )
        module._sd_notify("UNKNOWN=1")
        fake_notify.assert_not_called()

    def test_sd_notify_is_none_when_cysystemd_unavailable(self):
        """When cysystemd is not importable, _sd_notify must be None (graceful degradation)."""
        # Temporarily make cysystemd unimportable
        task_module_name = "refresh_task_jtn594_none_test"

        for mod_name in [
            "waveshare_epd",
            "gpiozero",
            "PIL",
            "PIL.Image",
            "PIL.ImageDraw",
            "PIL.ImageFont",
        ]:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = types.ModuleType(mod_name)

        spec = importlib.util.spec_from_file_location(
            task_module_name,
            SRC_DIR / "refresh_task" / "task.py",
        )
        module = importlib.util.module_from_spec(spec)

        class _RaisesImport:
            """Fake module finder that makes cysystemd unimportable."""

            def find_module(self, name, path=None):
                if name.startswith("cysystemd"):
                    return self

            def load_module(self, name):
                raise ImportError(f"Simulated missing: {name}")

        raiser = _RaisesImport()
        sys.meta_path.insert(0, raiser)
        try:
            if str(SRC_DIR) not in sys.path:
                sys.path.insert(0, str(SRC_DIR))
            # Remove any cached cysystemd modules
            for key in list(sys.modules.keys()):
                if key.startswith("cysystemd"):
                    del sys.modules[key]
            spec.loader.exec_module(module)
        finally:
            sys.meta_path.remove(raiser)
            # Clean up after ourselves
            if task_module_name in sys.modules:
                del sys.modules[task_module_name]

        assert module._sd_notify is None, (
            "_sd_notify should be None when cysystemd is unavailable, "
            "so _notify_watchdog() silently no-ops on non-systemd systems."
        )

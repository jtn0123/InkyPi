"""Browser gating must compose with pytest's own command-line selection."""

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

import pytest
from tests import conftest as policy


@pytest.mark.parametrize(
    "filename,flags,available,expected",
    [
        ("test_unit_probe.py", {}, False, "delegate"),
        ("test_browser_smoke.py", {}, True, "delegate"),
        ("test_browser_smoke.py", {}, False, "skip"),
        ("test_browser_smoke.py", {"SKIP_UI": "1"}, True, "skip"),
        ("test_axe_a11y.py", {"SKIP_A11Y": "1"}, True, "skip"),
        ("test_browser_smoke.py", {"SKIP_BROWSER": "true"}, True, "skip"),
        (
            "test_browser_smoke.py",
            {"SKIP_UI": "1", "REQUIRE_BROWSER_SMOKE": "1"},
            True,
            "delegate",
        ),
        (
            "test_browser_smoke.py",
            {"SKIP_BROWSER": "1", "REQUIRE_BROWSER_SMOKE": "1"},
            False,
            "required-error",
        ),
        (
            "test_cross_page_navigation_e2e.py",
            {"REQUIRE_BROWSER_SMOKE": "1"},
            False,
            "skip",
        ),
        (
            "test_axe_a11y.py",
            {"SKIP_BROWSER": "1", "REQUIRE_BROWSER_SMOKE": "1"},
            True,
            "skip",
        ),
    ],
)
def test_browser_collection_preserves_skip_and_required_policy(
    filename: str,
    flags: dict[str, str],
    available: bool,
    expected: Literal["delegate", "skip", "required-error"],
    monkeypatch: pytest.MonkeyPatch,
    pytestconfig: pytest.Config,
) -> None:
    for name in ("SKIP_BROWSER", "SKIP_UI", "SKIP_A11Y", "REQUIRE_BROWSER_SMOKE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in flags.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "_playwright_browser_available", lambda: available)
    collection_path = Path(filename)
    if expected == "required-error":
        with pytest.raises(RuntimeError, match="Chromium is unavailable"):
            policy.pytest_ignore_collect(collection_path, pytestconfig)
    else:
        result = policy.pytest_ignore_collect(collection_path, pytestconfig)
        if expected == "skip":
            assert result is True
        else:
            assert result is None


@pytest.mark.parametrize(
    "selection,excluded",
    [
        ("--ignore=tests/integration", "integration/test_browser_smoke.py"),
        ("--ignore=tests/test_excluded.py", "test_excluded.py"),
        ("--ignore-glob=*test_browser_smoke.py", "integration/test_browser_smoke.py"),
    ],
)
def test_cli_ignore_is_honored_by_actual_pytest(
    selection: str, excluded: str, tmp_path: Path
) -> None:
    root = Path(__file__).parents[2]
    tree = ast.parse((root / "tests/conftest.py").read_text())
    names = {"_is_truthy", "_browser_test_group", "pytest_ignore_collect"}
    constants = {"UI_BROWSER_TESTS", "A11Y_BROWSER_TESTS"}
    statements: list[ast.stmt] = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in names)
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in constants
                for target in node.targets
            )
        )
    ]
    # Execute the actual repository hook in a disposable pytest project. Only
    # browser availability is substituted, so no Chromium/network is needed.
    plugin = "import os\nfrom pathlib import Path\nfrom typing import Any\n"
    plugin += ast.unparse(ast.Module(body=statements, type_ignores=[]))
    plugin += "\ndef _playwright_browser_available():\n    return True\n"
    (tmp_path / "conftest.py").write_text(plugin)
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    tests = tmp_path / "tests"
    (tests / "integration").mkdir(parents=True)
    (tests / "test_selected.py").write_text("def test_selected():\n    pass\n")
    (tests / "test_excluded.py").write_text("def test_excluded():\n    pass\n")
    (tests / "integration/test_browser_smoke.py").write_text(
        "def test_browser_probe():\n    pass\n"
    )
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for name in (
        "SKIP_BROWSER",
        "SKIP_UI",
        "SKIP_A11Y",
        "REQUIRE_BROWSER_SMOKE",
        "PYTEST_ADDOPTS",
    ):
        env.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", selection],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "tests/test_selected.py::test_selected" in output
    assert f"tests/{excluded}::" not in output, output

"""Browser gating must compose with pytest's own command-line selection."""

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
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
            "required-error",
        ),
        # CI=true: a browser suite that would drop out for lack of Chromium
        # is a hard error, not a silent collection-ignore ...
        ("test_cross_page_navigation_e2e.py", {"CI": "true"}, False, "required-error"),
        ("test_axe_a11y.py", {"CI": "true"}, False, "required-error"),
        ("test_browser_smoke.py", {"CI": "true"}, True, "delegate"),
        # ... unless the job deselects the browser suites explicitly.
        (
            "test_cross_page_navigation_e2e.py",
            {"CI": "true", "SKIP_BROWSER": "1"},
            False,
            "skip",
        ),
        ("test_axe_a11y.py", {"CI": "true", "SKIP_A11Y": "1"}, False, "skip"),
        ("test_click_sweep.py", {"CI": "true", "SKIP_UI": "1"}, False, "skip"),
        ("test_unit_probe.py", {"CI": "true"}, False, "delegate"),
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
) -> None:
    for name in ("SKIP_BROWSER", "SKIP_UI", "SKIP_A11Y", "REQUIRE_BROWSER_SMOKE", "CI"):
        monkeypatch.delenv(name, raising=False)
    for name, value in flags.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "_playwright_browser_available", lambda: available)
    collection_path = Path(filename)
    # Model a run that targets the current directory, so the probe file is
    # one pytest was actually asked to collect.
    config = SimpleNamespace(
        args=["."], invocation_params=SimpleNamespace(dir=Path.cwd())
    )
    if expected == "required-error":
        with pytest.raises(RuntimeError, match="Chromium is unavailable"):
            policy.pytest_ignore_collect(collection_path, config)
    else:
        result = policy.pytest_ignore_collect(collection_path, config)
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
    names = {
        "_is_truthy",
        "_browser_test_group",
        "browser_required",
        "_targeted_by_args",
        "pytest_ignore_collect",
    }
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
        "CI",
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


@pytest.mark.parametrize(
    "raw,expected",
    [("", None), ("  ", None), ("1/2", (1, 2)), ("2/2", (2, 2)), (" 3/4 ", (3, 4))],
)
def test_parse_test_shard_accepts_valid_specs(
    raw: str, expected: tuple[int, int] | None
) -> None:
    assert policy._parse_test_shard(raw) == expected


@pytest.mark.parametrize("raw", ["1", "0/2", "3/2", "a/b", "1/0", "-1/2"])
def test_parse_test_shard_rejects_malformed_specs(raw: str) -> None:
    with pytest.raises(pytest.UsageError, match="INKYPI_TEST_SHARD"):
        policy._parse_test_shard(raw)


def test_shards_partition_the_selected_items_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Hook:
        def __init__(self) -> None:
            self.deselected: list[str] = []

        def pytest_deselected(self, items: list[str]) -> None:
            self.deselected.extend(items)

    class _Config:
        def __init__(self) -> None:
            self.hook = _Hook()

    all_items = [f"test_{i}" for i in range(7)]
    seen: list[str] = []
    for index in (1, 2, 3):
        monkeypatch.setenv("INKYPI_TEST_SHARD", f"{index}/3")
        items = list(all_items)
        config = _Config()
        policy.pytest_collection_modifyitems(config, items)  # type: ignore[arg-type]
        assert sorted(items + config.hook.deselected) == sorted(all_items)
        seen.extend(items)
    assert sorted(seen) == sorted(all_items)


def test_browser_modules_are_tagged_with_browser_marker() -> None:
    class _Item:
        def __init__(self, path: str) -> None:
            self.path = Path(path)
            self.markers: list[str] = []

        def add_marker(self, marker: pytest.MarkDecorator) -> None:
            self.markers.append(marker.name)

    browser_item = _Item("tests/integration/test_click_sweep.py")
    a11y_item = _Item("tests/integration/test_axe_a11y.py")
    plain_item = _Item("tests/unit/test_unit_probe.py")
    for item in (browser_item, a11y_item, plain_item):
        policy.pytest_itemcollected(item)  # type: ignore[arg-type]
    assert browser_item.markers == ["browser"]
    assert a11y_item.markers == ["browser"]
    assert plain_item.markers == []


@pytest.mark.parametrize("flags", [{"CI": "true"}, {"REQUIRE_BROWSER_SMOKE": "1"}])
def test_untargeted_browser_module_never_demands_a_browser(
    flags: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A browser module that is only a *sibling* of the requested files.

    pytest calls ``pytest_ignore_collect`` for every entry of a directory it
    collects from, so ``pytest tests/integration/test_api_contracts.py`` also
    visits ``test_click_sweep.py``. That must not error without Chromium.
    """
    for name in ("SKIP_BROWSER", "SKIP_UI", "SKIP_A11Y", "REQUIRE_BROWSER_SMOKE", "CI"):
        monkeypatch.delenv(name, raising=False)
    for name, value in flags.items():
        monkeypatch.setenv(name, value)

    def _no_probe() -> bool:
        raise AssertionError("untargeted modules must not probe for Chromium")

    monkeypatch.setattr(policy, "_playwright_browser_available", _no_probe)
    integration = tmp_path / "tests" / "integration"
    integration.mkdir(parents=True)
    config = SimpleNamespace(
        args=["tests/integration/test_api_contracts.py"],
        invocation_params=SimpleNamespace(dir=tmp_path),
    )
    result = policy.pytest_ignore_collect(integration / "test_click_sweep.py", config)
    assert result is None

"""Ratchet: tests that check front-end code by reading its text may not grow.

A source-text test reads a file under ``src/static/`` (or fetches
``/static/scripts/...`` or ``/sw.js`` from the app) and asserts that some
substring is, or is not, in it. It passes as long as the text is there,
whether or not the page works, so it misses real behaviour. New front-end
tests belong in a Playwright test under ``tests/integration/``.

The ratchet counts test functions, not files:

* every test in ``tests/static/``, which holds only this kind of test; and
* every test elsewhere under ``tests/`` that the scan below flags, unless
  ``ALLOWLIST`` names it.

The scan flags a test when it both refers to a script, a stylesheet or the
service worker (directly, or through a module-level constant or helper) and
asserts with ``in``/``not in`` or a string or regex search (directly, or
through a module-level helper). It is a heuristic: a test that reads the text
through a fixture defined in another file slips past it.

The count must equal ``CEILING``: the test fails when it goes up, and when it
goes down, so ``CEILING`` always matches the real count.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TESTS_DIR.parent
STATIC_TESTS_DIR = TESTS_DIR / "static"

# Lower this when a source-text test is removed or ported to Playwright.
CEILING = 360

_PLAYWRIGHT = "Playwright: loads the scripts into a real page and drives it"

# Tests outside tests/static/ that the scan flags but that do not check the
# page by its source text. A key is a whole file, or one test as
# "file::test" ("file::Class::test" for a method).
ALLOWLIST: dict[str, str] = {
    # Tooling: these check build, lint, install and vendor scripts.
    "tests/test_asset_bundling.py": "checks the bundler's fallback source list",
    "tests/test_dry_run_plugin.py": "checks the dry-run tool's vendor list",
    "tests/unit/test_asset_check.py": "checks the boot-time asset check",
    "tests/unit/test_biome_config.py": "checks the Biome lint configuration",
    "tests/unit/test_dev_watch_script.py": "checks what the dev watcher watches",
    "tests/unit/test_install_asset_build.py": "checks the install asset build",
    "tests/unit/test_install_scripts.py": "checks the install script",
    "tests/unit/test_precommit_config.py": "checks the pre-commit hooks",
    "tests/unit/test_update_vendors.py": "checks the vendor update script",
    # The path is data in these, not the text under test.
    "tests/integration/test_do_update_failure_surface.py"
    "::TestDirtyGeneratedCssDoesNotBlockCheckout"
    "::test_dirty_main_css_does_not_block_checkout": (
        "dirties main.css to test the update checkout"
    ),
    "tests/unit/test_updates_surface_errors.py"
    "::TestSynthesizeFailureFromJournal"
    "::test_synthesizes_last_failure_when_unit_failed_and_no_file": (
        "the path is text in a fake journal"
    ),
    "tests/test_client_error_forwarding.py"
    "::TestPostValidJson::test_all_accepted_fields_logged": (
        "the script URL is a field of the client error report"
    ),
    "tests/test_auth.py::TestAuthEnabled::test_private_static_requires_login": (
        "requests static URLs to test login gating"
    ),
    "tests/test_auth.py::TestSessionLifetime"
    "::test_pin_change_invalidates_existing_session": (
        "requests a static URL to test the session"
    ),
    "tests/test_service_worker.py::test_sw_js_content_type_javascript": (
        "checks the Content-Type header, not the body"
    ),
    # Behaviour tests that load the scripts into a browser.
    "tests/integration/test_plugin_add_to_playlist_ui.py": _PLAYWRIGHT,
    "tests/integration/test_plugin_draft_add_to_playlist.py": _PLAYWRIGHT,
    "tests/integration/test_plugin_form_async_job.py": _PLAYWRIGHT,
}

_STATIC_DIRS = ("scripts", "styles", "sw.js")
_SEARCH_METHODS = frozenset(
    {"search", "match", "fullmatch", "findall", "count", "find"}
    | {"startswith", "endswith"}
)

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _names_static_text(value: str) -> bool:
    if value == "/sw.js":
        return True
    return any(f"static/{name}" in value for name in _STATIC_DIRS)


def _path_segments(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _path_segments(node.left) + _path_segments(node.right)
    return [node]


def _string_values(nodes: list[ast.expr]) -> list[str]:
    return [
        (
            node.value
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else ""
        )
        for node in nodes
    ]


def _refers_to_static_text(node: ast.AST) -> bool:
    """True if *node* names a script, a stylesheet or the service worker.

    Catches ``"src/static/scripts/app.js"``, ``ROOT / "static" / "scripts"``
    and ``Path(root, "static", "styles")``.
    """
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and _names_static_text(child.value)
        ):
            return True
        parts: list[str] = []
        if isinstance(child, ast.BinOp) and isinstance(child.op, ast.Div):
            parts = _string_values(_path_segments(child))
        elif isinstance(child, ast.Call):
            parts = _string_values(child.args)
        for first, second in zip(parts, parts[1:], strict=False):
            if first.rstrip("/").endswith("static") and (
                second.split("/")[0] in _STATIC_DIRS
            ):
                return True
    return False


def _asserts_on_substrings(node: ast.AST) -> bool:
    """True if *node* asserts that text contains, or lacks, something.

    Membership in a literal tuple, list, set or dict (``status in (200,
    304)``) is not a substring check.
    """
    for child in ast.walk(node):
        if not isinstance(child, ast.Assert):
            continue
        for part in ast.walk(child.test):
            if isinstance(part, ast.Compare):
                literal = (ast.Tuple, ast.List, ast.Set, ast.Dict)
                if any(isinstance(op, ast.In | ast.NotIn) for op in part.ops) and not (
                    any(isinstance(right, literal) for right in part.comparators)
                ):
                    return True
            if (
                isinstance(part, ast.Call)
                and isinstance(part.func, ast.Attribute)
                and part.func.attr in _SEARCH_METHODS
            ):
                return True
    return False


def _names_used(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
    return names


def _test_functions(tree: ast.Module) -> Iterator[tuple[str, FunctionNode]]:
    for node in tree.body:
        if isinstance(node, FunctionNode) and node.name.startswith("test_"):
            yield node.name, node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, FunctionNode) and item.name.startswith("test_"):
                    yield f"{node.name}::{item.name}", item


def _module_helpers(tree: ast.Module) -> dict[str, ast.stmt]:
    """Module-level names other than tests, mapped to their definitions."""
    helpers: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, FunctionNode | ast.ClassDef):
            if not node.name.startswith(("test_", "Test")):
                helpers[node.name] = node
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        helpers[name.id] = node
    return helpers


def flagged_tests(source: str) -> list[str]:
    """Names of the tests in *source* that assert on front-end source text."""
    tree = ast.parse(source)
    helpers = _module_helpers(tree)
    reads = {name for name, node in helpers.items() if _refers_to_static_text(node)}
    asserts = {
        name
        for name, node in helpers.items()
        if isinstance(node, FunctionNode) and _asserts_on_substrings(node)
    }
    # A helper that uses a tainted name is tainted too.
    changed = True
    while changed:
        changed = False
        for name, node in helpers.items():
            used = _names_used(node)
            if name not in reads and used & reads:
                reads.add(name)
                changed = True
            if (
                name not in asserts
                and isinstance(node, FunctionNode)
                and used & asserts
            ):
                asserts.add(name)
                changed = True
    flagged: list[str] = []
    for name, node in _test_functions(tree):
        used = _names_used(node)
        if (_refers_to_static_text(node) or used & reads) and (
            _asserts_on_substrings(node) or used & asserts
        ):
            flagged.append(name)
    return flagged


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _is_allowlisted(test_id: str) -> bool:
    path = test_id.split("::", 1)[0]
    return test_id in ALLOWLIST or path in ALLOWLIST


@cache
def _flagged_outside_static() -> tuple[str, ...]:
    """Every flagged test outside tests/static/, allowlisted or not."""
    this_file = Path(__file__).resolve()
    found: list[str] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        # This file's own scanner examples would flag themselves.
        if path.is_relative_to(STATIC_TESTS_DIR) or path.resolve() == this_file:
            continue
        source = path.read_text(encoding="utf-8")
        found.extend(f"{_relative(path)}::{name}" for name in flagged_tests(source))
    return tuple(found)


@cache
def _static_dir_tests() -> tuple[str, ...]:
    found: list[str] = []
    for path in sorted(STATIC_TESTS_DIR.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(f"{_relative(path)}::{name}" for name, _ in _test_functions(tree))
    return tuple(found)


def _counted_tests() -> list[str]:
    elsewhere = [t for t in _flagged_outside_static() if not _is_allowlisted(t)]
    return [*_static_dir_tests(), *elsewhere]


def test_source_text_test_count_matches_ceiling() -> None:
    counted = _counted_tests()
    count = len(counted)
    outside = [t for t in counted if not t.startswith("tests/static/")]
    assert count <= CEILING, (
        f"{count} tests check front-end code by its source text, over the "
        f"ceiling of {CEILING}. Write a Playwright test in tests/integration/ "
        "instead. If a flagged test does not check the page by its text, add "
        "it to ALLOWLIST in tests/unit/test_static_text_tests_ratchet.py with "
        "the reason. Flagged outside tests/static/:\n  " + "\n  ".join(outside)
    )
    assert count >= CEILING, (
        f"{count} tests check front-end code by its source text, under the "
        f"ceiling of {CEILING}. Lower CEILING in "
        f"tests/unit/test_static_text_tests_ratchet.py to {count}."
    )


def test_every_allowlist_entry_still_matches_a_flagged_test() -> None:
    flagged = _flagged_outside_static()
    stale = [
        key
        for key in ALLOWLIST
        if not any(t == key or t.startswith(f"{key}::") for t in flagged)
    ]
    assert not stale, (
        "These ALLOWLIST entries no longer match a flagged test. Remove them: "
        + ", ".join(stale)
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from pathlib import Path\n"
            'JS = Path("src/static/scripts/app.js")\n'
            "def test_it():\n"
            '    assert "addEventListener" in JS.read_text()\n',
            id="module-constant",
        ),
        pytest.param(
            "def test_it(client):\n"
            '    body = client.get("/static/scripts/app.js").get_data(as_text=True)\n'
            '    assert "export" not in body\n',
            id="served-script",
        ),
        pytest.param(
            "import re\n"
            "ROOT = object()\n"
            "def _read(name):\n"
            '    return (ROOT / "src" / "static" / "styles" / name).read_text()\n'
            "def test_it():\n"
            '    assert re.search(r"\\.card", _read("main.css"))\n',
            id="path-segments-and-regex",
        ),
        pytest.param(
            "def _js():\n"
            '    return open("src/static/scripts/app.js").read()\n'
            "def _has(text, needle):\n"
            "    assert needle in text\n"
            "class TestPage:\n"
            "    def test_it(self):\n"
            '        _has(_js(), "init(")\n',
            id="helpers-in-a-class",
        ),
        pytest.param(
            "def test_it(client):\n"
            '    assert "CACHE_NAME" in client.get("/sw.js").text\n',
            id="service-worker",
        ),
    ],
)
def test_scan_flags_source_text_tests(source: str) -> None:
    assert len(flagged_tests(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def test_it(client):\n"
            '    resp = client.get("/static/scripts/app.js")\n'
            "    assert resp.status_code in (200, 304)\n",
            id="status-in-a-literal-tuple",
        ),
        pytest.param(
            "def test_it(client):\n"
            '    assert "Saved" in client.get("/settings").text\n',
            id="page-text-not-source",
        ),
        pytest.param(
            "def test_it(tmp_path):\n"
            '    (tmp_path / "static" / "images").mkdir(parents=True)\n'
            '    assert "x" in "xyz"\n',
            id="static-images",
        ),
        pytest.param(
            "def helper_test(client):\n"
            '    assert "x" in client.get("/static/scripts/app.js").text\n',
            id="not-a-test",
        ),
    ],
)
def test_scan_ignores_other_tests(source: str) -> None:
    assert flagged_tests(source) == []

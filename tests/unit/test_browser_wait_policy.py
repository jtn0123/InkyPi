"""Browser tests wait for conditions, not for fixed amounts of time.

``page.wait_for_timeout(ms)`` pauses for a fixed time. Used to wait for
something to happen, it is either longer than needed (slow tests) or too short
on a loaded CI machine (flaky tests). Wait for the thing itself instead:
``page.expect_response`` for a request, ``expect(locator)`` or
``page.wait_for_function`` for a DOM change, and
``tests/integration/browser_helpers.py`` for a page's start-up requests.

This test scans ``tests/`` and allows a fixed pause only when:

* it is a short poll: a number literal of at most 100 ms inside the body of a
  ``for`` or ``while`` loop that re-checks a condition; or
* it is listed in :data:`ALLOWED_FIXED_WAITS` with the reason the passing time
  is itself the point (a load test's pacing, a window in which nothing should
  happen).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

# Longest pause allowed as a poll interval inside a loop.
MAX_POLL_MS = 100

# (path under tests/, enclosing function, argument as written) -> reason.
ALLOWED_FIXED_WAITS: dict[tuple[str, str, str], str] = {
    (
        "integration/test_click_sweep.py",
        "_click_one",
        "_CLICK_SETTLE_MS",
    ): (
        "The sweep's design: every click gets the same short pause before the "
        "DOM snapshot, and the snapshot asks whether anything changed at all, "
        "so there is no particular change to wait for."
    ),
    (
        "integration/test_cross_page_navigation_e2e.py",
        "test_all_pages_load_without_js_errors",
        "1000",
    ): (
        "Observation window: the test checks that a loaded page logs no errors "
        "for a second (timers, late handlers). No event marks that."
    ),
    (
        "integration/test_cross_page_navigation_e2e.py",
        "test_plugin_page_loads_without_errors",
        "1000",
    ): (
        "Observation window: the test checks that a loaded page logs no errors "
        "for a second (timers, late handlers). No event marks that."
    ),
    (
        "integration/test_jtn_720_721_722_journeys.py",
        "test_jtn_720_first_run_setup_add_schedule_refresh_history",
        "500",
    ): (
        "Poll interval of a deadline loop in which every pass is a full page "
        "load of /history; a shorter interval would mostly add page loads."
    ),
    (
        "integration/test_sustained_load.py",
        "_collect_candidates",
        "200",
    ): (
        "Load-test pacing: a fixed pause after each page load keeps the load "
        "steady; waiting for the page to go idle would soften it."
    ),
    (
        "integration/test_sustained_load.py",
        "test_sustained_handler_load",
        "_CLICK_SETTLE_MS",
    ): "Load-test pacing: a fixed pause per click keeps the click rate steady.",
}


@dataclass(frozen=True)
class FixedWait:
    """One ``wait_for_timeout`` call found in the test sources."""

    path: str
    function: str
    argument: str
    line: int
    in_loop: bool

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.function, self.argument)

    def is_short_poll(self) -> bool:
        """True for a number literal of at most MAX_POLL_MS inside a loop body."""
        try:
            value = ast.literal_eval(self.argument)
        except ValueError:
            return False
        return (
            self.in_loop
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value <= MAX_POLL_MS
        )

    def __str__(self) -> str:
        return (
            f"tests/{self.path}:{self.line} in {self.function}: "
            f"wait_for_timeout({self.argument})"
        )


class _FixedWaitFinder(ast.NodeVisitor):
    """Collect ``*.wait_for_timeout(...)`` calls with their function and loop."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.found: list[FixedWait] = []
        self._scopes: list[str] = []
        # Loop depth per enclosing function: a loop around a ``def`` does not
        # make the calls inside that function part of the loop.
        self._loop_depth = [0]

    def _visit_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._scopes.append(node.name)
        self._loop_depth.append(0)
        self.generic_visit(node)
        self._loop_depth.pop()
        self._scopes.pop()

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scopes.append(node.name)
        self.generic_visit(node)
        self._scopes.pop()

    def _visit_loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        # Only the loop body repeats; the header and ``else`` run once.
        header = (
            [node.test] if isinstance(node, ast.While) else [node.target, node.iter]
        )
        for child in header:
            self.visit(child)
        self._loop_depth[-1] += 1
        for statement in node.body:
            self.visit(statement)
        self._loop_depth[-1] -= 1
        for statement in node.orelse:
            self.visit(statement)

    visit_For = _visit_loop
    visit_AsyncFor = _visit_loop
    visit_While = _visit_loop

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "wait_for_timeout"
        ):
            argument = node.args[0] if node.args else None
            if argument is None:
                argument = next(
                    (kw.value for kw in node.keywords if kw.arg == "timeout"), None
                )
            self.found.append(
                FixedWait(
                    path=self.path,
                    function=".".join(self._scopes) or "<module>",
                    argument=ast.unparse(argument) if argument is not None else "",
                    line=node.lineno,
                    in_loop=self._loop_depth[-1] > 0,
                )
            )
        self.generic_visit(node)


def find_fixed_waits(root: Path) -> list[FixedWait]:
    """Every ``wait_for_timeout`` call in the Python files under ``root``."""
    found: list[FixedWait] = []
    for source in sorted(root.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        finder = _FixedWaitFinder(source.relative_to(root).as_posix())
        finder.visit(ast.parse(source.read_text(encoding="utf-8"), str(source)))
        found.extend(finder.found)
    return found


def find_violations(
    root: Path, allowed: dict[tuple[str, str, str], str] | None = None
) -> list[FixedWait]:
    """Fixed waits under ``root`` that are neither short polls nor allowlisted."""
    allowed = ALLOWED_FIXED_WAITS if allowed is None else allowed
    return [
        wait
        for wait in find_fixed_waits(root)
        if not wait.is_short_poll() and wait.key not in allowed
    ]


def test_browser_tests_wait_for_conditions_not_fixed_sleeps() -> None:
    violations = find_violations(TESTS_ROOT)
    assert not violations, (
        "Fixed sleeps found. Wait for the condition instead (expect_response, "
        "expect(locator), wait_for_function, browser_helpers.RequestTracker); "
        f"a poll inside a loop may pause up to {MAX_POLL_MS} ms. If the passing "
        "time is itself the point, add the call to ALLOWED_FIXED_WAITS in "
        "tests/unit/test_browser_wait_policy.py with the reason.\n  "
        + "\n  ".join(str(wait) for wait in violations)
    )


def test_allowlist_has_no_stale_entries() -> None:
    present = {wait.key for wait in find_fixed_waits(TESTS_ROOT)}
    stale = sorted(set(ALLOWED_FIXED_WAITS) - present)
    assert not stale, f"ALLOWED_FIXED_WAITS lists calls that no longer exist: {stale}"


def test_allowlist_entries_give_a_reason() -> None:
    assert all(reason.strip() for reason in ALLOWED_FIXED_WAITS.values())


def test_finder_tells_polls_from_fixed_sleeps(tmp_path: Path) -> None:
    (tmp_path / "test_probe.py").write_text(
        """
SETTLE_MS = 50

def poll(page):
    while not done():
        page.wait_for_timeout(50)
    for _ in range(3):
        page.wait_for_timeout(timeout=100)

def sleeps(page):
    page.wait_for_timeout(50)
    page.wait_for_timeout(SETTLE_MS)
    while True:
        page.wait_for_timeout(250)
    for _ in range(3):
        pass
    else:
        page.wait_for_timeout(10)

class Helper:
    def method(self, page):
        for _ in range(3):
            def inner():
                page.wait_for_timeout(10)
""",
        encoding="utf-8",
    )
    violations = find_violations(tmp_path, allowed={})
    assert [(wait.function, wait.argument, wait.line) for wait in violations] == [
        ("sleeps", "50", 11),
        ("sleeps", "SETTLE_MS", 12),
        ("sleeps", "250", 14),
        ("sleeps", "10", 18),
        ("Helper.method.inner", "10", 24),
    ]

    allowed = {("test_probe.py", "sleeps", "SETTLE_MS"): "pacing"}
    assert ("test_probe.py", "sleeps", "SETTLE_MS") not in {
        wait.key for wait in find_violations(tmp_path, allowed=allowed)
    }

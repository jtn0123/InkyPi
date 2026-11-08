"""Guard against string patch targets that cannot affect the code under test.

``patch("pkg.mod.name")`` / ``monkeypatch.setattr("pkg.mod.name", ...)`` only
changes behaviour if code looks ``name`` up in ``pkg.mod`` at call time. After
a module split it is easy to leave a test patching a *re-export* (a name the
module merely imports, or aliases, and never uses itself): the patch succeeds,
but the real lookup happens in another module, so the test silently stops
exercising the path it claims to.

This test parses (never imports) every test file and every targeted project
module, so it is fast and has no side effects. For each string target that
names an attribute directly on a module under ``src/`` it checks that:

* the module binds the name at top level, and
* if the name is only *imported/aliased* there, the module also reads it.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TESTS = ROOT / "tests"

# Targets that are effective even though the module never reads the name
# itself. Each entry must say where the real lookup happens.
_ALLOWED_UNREAD_REEXPORTS: dict[str, str] = {
    # security_middleware resolves it with getattr(inkypi_mod, "pop_hot_reload_info").
    "inkypi.pop_hot_reload_info": "looked up via getattr on the inkypi module",
    # inkypi does ``from refresh_task import RefreshTask``; the test patches the
    # package attribute *before* re-importing inkypi, so inkypi binds the mock.
    "refresh_task.RefreshTask": "bound by inkypi when it is re-imported under the patch",
}


def _patch_kind(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name) and func.id == "patch":
        return "patch"
    if isinstance(func, ast.Attribute):
        if func.attr == "patch":
            return "patch"
        if func.attr in ("setattr", "delattr"):
            return "setattr"
    return None


def _is_lenient(call: ast.Call) -> bool:
    """``create=True`` / ``raising=False`` deliberately allow missing names."""
    for kw in call.keywords:
        if not isinstance(kw.value, ast.Constant):
            continue
        if kw.arg == "create" and kw.value.value is True:
            return True
        if kw.arg == "raising" and kw.value.value is False:
            return True
    return False


@cache
def _collect_targets() -> dict[str, list[tuple[str, int, bool]]]:
    targets: dict[str, list[tuple[str, int, bool]]] = {}
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            kind = _patch_kind(node)
            first = node.args[0]
            if kind is None or not isinstance(first, ast.Constant):
                continue
            if not isinstance(first.value, str) or "." not in first.value:
                continue
            # monkeypatch.setattr(obj, "name", value) puts the name second.
            if kind == "setattr" and len(node.args) > 2:
                continue
            rel = str(path.relative_to(ROOT))
            targets.setdefault(first.value, []).append(
                (rel, node.lineno, _is_lenient(node))
            )
    return targets


def _module_file(dotted: str) -> Path | None:
    base = SRC.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


@cache
def _module_names(
    path: Path,
) -> tuple[frozenset[str], frozenset[str], frozenset[str], bool]:
    """Return (locally defined, import/alias bound, read names, dynamic?)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined: set[str] = set()
    imported: set[str] = set()
    dynamic = False

    def bind_targets(stmt: ast.stmt, into: set[str]) -> None:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                into.add(sub.id)

    def visit_top(body: list[ast.stmt]) -> None:
        nonlocal dynamic
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(stmt.name)
                if stmt.name == "__getattr__":
                    dynamic = True
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                for alias in stmt.names:
                    if alias.name == "*":
                        dynamic = True
                    imported.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                value = stmt.value
                # ``name = other_module.name`` is an alias, like an import.
                is_alias = isinstance(value, (ast.Attribute, ast.Name))
                bind_targets(stmt, imported if is_alias else defined)
            elif isinstance(stmt, (ast.If, ast.Try, ast.With)):
                for block in ("body", "orelse", "finalbody"):
                    visit_top(getattr(stmt, block, []) or [])
                for handler in getattr(stmt, "handlers", []):
                    visit_top(handler.body)

    visit_top(tree.body)
    read = frozenset(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    )
    return frozenset(defined), frozenset(imported), read, dynamic


def _check(target: str, lenient: bool) -> str | None:
    parts = target.split(".")
    # Only targets of the form ``<project module>.<name>``; deeper paths patch
    # an attribute of some other object (e.g. ``mod.os.path.exists``).
    module_path = _module_file(".".join(parts[:-1]))
    if module_path is None:
        return None
    name = parts[-1]
    defined, imported, read, dynamic = _module_names(module_path)
    if name in defined:
        return None
    if name not in imported:
        # Star imports / module ``__getattr__`` can supply names dynamically.
        if lenient or dynamic:
            return None
        return f"{module_path.relative_to(ROOT)} has no {name!r}"
    if name in read or target in _ALLOWED_UNREAD_REEXPORTS:
        return None
    return (
        f"{name!r} is only imported/aliased in {module_path.relative_to(ROOT)} "
        "and never read there; patch it where it is looked up"
    )


def test_string_patch_targets_hit_a_real_lookup() -> None:
    problems = []
    for target, locations in sorted(_collect_targets().items()):
        lenient = all(loc[2] for loc in locations)
        reason = _check(target, lenient)
        if reason:
            where = ", ".join(f"{p}:{n}" for p, n, _ in locations)
            problems.append(f"{target}: {reason} (used at {where})")
    assert not problems, "Ineffective patch targets:\n" + "\n".join(problems)


def test_allowlist_entries_are_still_needed() -> None:
    targets = _collect_targets()
    stale = [t for t in _ALLOWED_UNREAD_REEXPORTS if t not in targets]
    assert not stale, f"Remove stale allowlist entries: {stale}"


def test_guard_flags_an_unread_reexport(tmp_path: Path) -> None:
    """Self-check: the analysis really detects the bug class it guards."""
    mod = tmp_path / "mod.py"
    mod.write_text(
        "from other import used, unused\n"
        "alias = other_mod.thing\n"
        "def local():\n"
        "    return used()\n"
    )
    defined, imported, read, dynamic = _module_names(mod)
    assert "local" in defined and not dynamic
    assert {"used", "unused", "alias"} <= imported
    assert "used" in read
    assert "unused" not in read and "alias" not in read

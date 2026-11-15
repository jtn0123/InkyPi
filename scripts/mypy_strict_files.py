#!/usr/bin/env python3
"""Print the source files in the strict mypy subset, one per line.

``mypy.ini`` is the only list: every ``[mypy-<module>]`` section with
``strict = True`` is in the subset. ``scripts/lint.sh`` runs
``mypy --strict`` on what this prints, so adding a module is a two-line
``mypy.ini`` change. It exits 1 if a listed module has no source file, so a
rename can't silently drop a module from the check.
"""

from __future__ import annotations

import configparser
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTION_PREFIX = "mypy-"


def strict_modules(ini_path: Path) -> list[str]:
    """Return the module names ``mypy.ini`` marks ``strict = True``, in file order."""
    parser = configparser.ConfigParser()
    parser.read(ini_path, encoding="utf-8")
    modules = []
    for section in parser.sections():
        if not section.startswith(SECTION_PREFIX):
            continue
        if not parser.getboolean(section, "strict", fallback=False):
            continue
        module = section.removeprefix(SECTION_PREFIX)
        if "*" in module or "," in module:
            raise ValueError(f"strict section [{section}] must name one module")
        modules.append(module)
    return modules


def module_file(module: str, src: Path) -> Path | None:
    """Return the source file for *module* under *src*, or None if there isn't one."""
    base = src.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    src = ROOT / "src"
    missing = []
    for module in strict_modules(ROOT / "mypy.ini"):
        path = module_file(module, src)
        if path is None:
            missing.append(module)
            continue
        print(path.relative_to(ROOT).as_posix())
    if missing:
        print(
            f"mypy.ini lists strict modules with no source file: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

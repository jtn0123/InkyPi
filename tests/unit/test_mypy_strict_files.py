"""``mypy.ini`` is the only list of strict modules (I9)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "mypy_strict_files.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mypy_strict_files", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


strict_files = _load()


def test_reads_only_strict_sections(tmp_path: Path) -> None:
    ini = tmp_path / "mypy.ini"
    ini.write_text(
        "[mypy]\nstrict_equality = True\n\n"
        "[mypy-utils.a]\nstrict = True\n\n"
        "[mypy-utils.b]\nstrict = False\n\n"
        "[mypy-waitress.*]\nignore_missing_imports = True\n\n"
        "[mypy-model]\nstrict = True\n",
        encoding="utf-8",
    )

    assert strict_files.strict_modules(ini) == ["utils.a", "model"]


def test_rejects_a_wildcard_strict_section(tmp_path: Path) -> None:
    ini = tmp_path / "mypy.ini"
    ini.write_text("[mypy-utils.*]\nstrict = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="one module"):
        strict_files.strict_modules(ini)


def test_resolves_modules_and_packages(tmp_path: Path) -> None:
    (tmp_path / "utils").mkdir()
    (tmp_path / "utils" / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")

    assert strict_files.module_file("utils.a", tmp_path) == tmp_path / "utils/a.py"
    assert strict_files.module_file("pkg", tmp_path) == tmp_path / "pkg/__init__.py"
    assert strict_files.module_file("utils.gone", tmp_path) is None


def test_every_listed_module_has_a_source_file() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    files = result.stdout.split()
    assert "src/utils/http_utils.py" in files
    assert all((ROOT / f).is_file() for f in files)


def test_lint_script_reads_the_list_instead_of_repeating_it() -> None:
    lint = (ROOT / "scripts" / "lint.sh").read_text(encoding="utf-8")

    assert "scripts/mypy_strict_files.py" in lint
    assert "mypy --strict \\" not in lint, "lint.sh hard-codes a strict list again"

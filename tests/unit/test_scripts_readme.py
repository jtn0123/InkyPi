"""scripts/README.md describes exactly the files in scripts/."""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
README = SCRIPTS_DIR / "README.md"
_NOT_LISTED = {"README.md", "__init__.py", "__pycache__"}


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_every_script_is_described() -> None:
    readme = _readme()
    missing = [
        path.name
        for path in sorted(SCRIPTS_DIR.iterdir())
        if path.name not in _NOT_LISTED
        and not path.name.startswith(".")
        and f"`{path.name}`" not in readme
    ]
    assert not missing, f"describe these in scripts/README.md: {missing}"


def test_readme_names_only_scripts_that_exist() -> None:
    # Bare file names in backticks refer to scripts/; paths with a slash
    # point elsewhere and are not checked here.
    named = set(re.findall(r"`([\w.-]+\.(?:py|sh|txt))`", _readme()))
    gone = sorted(name for name in named if not (SCRIPTS_DIR / name).exists())
    assert not gone, f"scripts/README.md describes missing scripts: {gone}"

"""The installed app version, read the same way by every caller."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Values a VERSION file can hold that are not a shipped version: the
#: unexpanded template a broken release left behind (JTN-595), and the
#: project's pre-release bootstrap value.
_PLACEHOLDERS = frozenset({"{version}", "0.1.0"})


def read_app_version(repo_root: Path = REPO_ROOT) -> str:
    """Return the installed application version.

    Resolution order (JTN-624):

    1. ``VERSION`` at the repo root, written by the release pipeline,
       unless it is empty or a placeholder.
    2. ``[project].version`` from ``pyproject.toml``.
    3. ``"unknown"`` if both fail.
    """
    try:
        value = (repo_root / "VERSION").read_text().strip()
        if value and value not in _PLACEHOLDERS:
            return value
    except (OSError, ValueError):
        pass

    # Imported here: a real install has VERSION, and tomllib costs the
    # Pi four modules and about 0.5 MB it would otherwise never use.
    import tomllib

    try:
        with (repo_root / "pyproject.toml").open("rb") as f:
            data = tomllib.load(f)
        version = data.get("project", {}).get("version")
        if isinstance(version, str) and version:
            return version
    except (OSError, ValueError):
        pass

    return "unknown"

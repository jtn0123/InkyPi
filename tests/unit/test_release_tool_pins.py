"""The release jobs install their tools from hashed pins.

release.yml can push tags and publish releases, and build-wheelhouse.yml
builds the wheels every Pi installs. A floating dependency or a re-tagged
base image in either would ship unreviewed code.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"


def _groups() -> dict[str, list[object]]:
    groups: dict[str, list[object]] = tomllib.loads(
        (REPO / "pyproject.toml").read_text()
    )["dependency-groups"]
    return groups


def test_release_group_holds_the_release_tools() -> None:
    names = {
        re.split(r"[=<>;\s]", str(req), maxsplit=1)[0].lower()
        for req in _groups()["release"]
    }
    assert {"python-semantic-release", "cyclonedx-bom", "gitpython"} <= names


def test_dev_environment_still_has_the_release_tools() -> None:
    assert {"include-group": "release"} in _groups()["dev"]


def test_release_job_installs_the_locked_group_with_hashes() -> None:
    workflow = (WORKFLOWS / "release.yml").read_text()
    assert "uv export --frozen --only-group release" in workflow
    assert "pip install --require-hashes --no-deps" in workflow
    # No tool installed by name, which would float its dependencies.
    assert not re.search(r"pip install [a-z][\w.-]*==", workflow)


def test_wheelhouse_builds_in_a_pinned_image_with_hashed_pip() -> None:
    workflow = (WORKFLOWS / "build-wheelhouse.yml").read_text()
    code = [line for line in workflow.splitlines() if not line.lstrip().startswith("#")]
    images = [m for line in code for m in re.findall(r"debian:\S+", line)]
    assert images, "the wheelhouse no longer names a Debian image"
    for image in images:
        assert re.fullmatch(r"debian:trixie-slim@sha256:[0-9a-f]{64}", image), image
    assert "pip install --require-hashes" in workflow
    assert "--upgrade pip" not in workflow

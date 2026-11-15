"""Biome lints the web scripts the same way in the pre-commit hook and in CI.

biome.json holds the rules. The Biome version is pinned in three places (the
config's $schema, the pre-commit mirror's rev, and CI's setup-biome input), so
a bump that misses one would lint with two different rule sets.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BIOME_JSON = REPO_ROOT / "biome.json"
PRECOMMIT = REPO_ROOT / ".pre-commit-config.yaml"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCRIPTS = REPO_ROOT / "src" / "static" / "scripts"

BIOME_MIRROR = "https://github.com/biomejs/pre-commit"


def _config() -> dict[str, Any]:
    config = json.loads(BIOME_JSON.read_text())
    assert isinstance(config, dict)
    return config


def _hook_repo() -> dict[str, Any]:
    config = yaml.safe_load(PRECOMMIT.read_text())
    repos = [repo for repo in config["repos"] if repo["repo"] == BIOME_MIRROR]
    assert len(repos) == 1
    repo = repos[0]
    assert isinstance(repo, dict)
    return repo


def _ci_steps() -> list[dict[str, Any]]:
    steps = yaml.safe_load(CI_YML.read_text())["jobs"]["lint"]["steps"]
    assert isinstance(steps, list)
    return steps


def _setup_step() -> dict[str, Any]:
    setups = [
        step
        for step in _ci_steps()
        if str(step.get("uses", "")).startswith("biomejs/setup-biome@")
    ]
    assert len(setups) == 1
    return setups[0]


def test_one_biome_version_everywhere() -> None:
    schema = _config()["$schema"]
    match = re.fullmatch(
        r"https://biomejs\.dev/schemas/(\d+\.\d+\.\d+)/schema\.json", schema
    )
    assert match, schema
    version = match.group(1)
    assert _hook_repo()["rev"] == f"v{version}"
    assert str(_setup_step()["with"]["version"]) == version


def test_setup_action_is_pinned_by_commit() -> None:
    ref = _setup_step()["uses"].split("@", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{40}", ref), ref


def test_lint_only_and_warnings_fail() -> None:
    config = _config()
    # Lint only: no file is reformatted, and import sorting is off.
    assert config["formatter"]["enabled"] is False
    assert config["assist"]["enabled"] is False
    # A rule that only warns would never fail anything.
    hooks = _hook_repo()["hooks"]
    assert [hook["id"] for hook in hooks] == ["biome-ci"]
    assert "--error-on-warnings" in hooks[0]["args"]
    runs = [str(step.get("run", "")) for step in _ci_steps()]
    assert "biome ci --error-on-warnings" in runs


def test_hook_and_ci_lint_the_same_files() -> None:
    includes = _config()["files"]["includes"]
    assert includes[0] == "src/static/scripts/**/*.js"
    hook = _hook_repo()["hooks"][0]
    assert re.match(hook["files"], "src/static/scripts/playlist/form.js")
    assert not re.match(hook["files"], "tests/fixtures/async_refresh_probe.js")
    # The service worker sits outside scripts/ and is linted too.
    assert "src/static/sw.js" in includes
    assert re.match(hook["files"], "src/static/sw.js")


def test_local_lint_runs_biome_like_ci() -> None:
    # A green scripts/lint.sh must mean a green CI lint job, which runs Biome.
    lint = (REPO_ROOT / "scripts" / "lint.sh").read_text()
    assert "pre-commit run biome-ci --all-files" in lint
    assert "BIOME_EXIT -ne 0" in lint


def test_declared_globals_are_published() -> None:
    # Each name in javascript.globals is a function another script calls by
    # bare name. If its definition goes away, the stale entry would hide a
    # ReferenceError from noUndeclaredVariables.
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(SCRIPTS.rglob("*.js"))
    )
    for name in _config()["javascript"]["globals"]:
        assert f"globalThis.{name} = {name};" in source, name


def test_downloaded_vendor_scripts_are_not_linted() -> None:
    # install/update_vendors.sh writes third-party files into
    # src/static/scripts/. They are git-ignored, but a bare `biome ci` walks
    # the directory itself; Biome's git-ignore support can't be used because
    # several tracked scripts match the same ignore pattern.
    vendors = (REPO_ROOT / "install" / "update_vendors.sh").read_text()
    outputs = re.findall(r"\|(src/static/scripts/[^|]+\.js)\|", vendors)
    assert outputs
    includes = _config()["files"]["includes"]
    for path in outputs:
        assert path.endswith(".min.js") or f"!{path}" in includes, path

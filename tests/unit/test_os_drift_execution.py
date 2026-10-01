"""Execute workflow shell and summary code against representative runner inputs."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        yaml.safe_load((ROOT / ".github/workflows/os-drift-nightly.yml").read_text()),
    )


def test_container_shell_supports_pipefail(tmp_path: Path) -> None:
    job = workflow()["jobs"]["drift-check"]
    step = job["steps"][0]
    shell = step.get("shell", job.get("defaults", {}).get("run", {}).get("shell", "sh"))
    result = subprocess.run(
        [shell, "-c", step["run"]],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "EVENT_NAME": "schedule",
            "SELECTED_CODENAME": "all",
            "MATRIX_CODENAME": "bookworm",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
    )
    assert result.returncode == 0, result.stderr


def test_disabled_issues_still_publish_summary(tmp_path: Path) -> None:
    job = workflow()["jobs"]["open-issue-on-failure"]
    script = next(
        s["with"]["script"]
        for s in job["steps"]
        if "with" in s and "script" in s["with"]
    )
    probe = """
const assert = require('assert');
let summary = '', issues = 0;
const core = {
 info: () => {}, warning: () => {},
 summary: { addRaw: s => { summary += s; return core.summary; }, write: async () => {} }
};
const github = { rest: {
 repos: {get: async () => ({data: {has_issues: false}})},
 issues: {
  listForRepo: async () => ({data: []}),
  create: async () => {issues++; throw Error('Issues are disabled');}
 }
}};
const context = {repo: {owner: 'fixture', repo: 'inkypi'}};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('require','github','core','context', SCRIPT)(require,github,core,context)
 .then(() => {assert(summary.includes('nightly OS drift detector failed')); assert.equal(issues,0);})
 .catch(error => {console.error(error); process.exitCode=1;});
""".replace("SCRIPT", json.dumps(script))
    result = subprocess.run(
        ["node", "-e", probe], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr

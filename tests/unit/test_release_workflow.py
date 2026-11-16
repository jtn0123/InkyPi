"""A release stays a draft until all its files are attached, then publishes.

Once GitHub's immutable releases are on, a published release's files and tag
can't change. So release.yml creates the release as a draft, attaches the
SBOM, the wheelhouse and the Pi image to it, and publishes it last.
semantic-release pushes the version commit and tag with the release deploy
key, the only actor allowed past main's required "CI gate" check.

The step scripts run here as written in the workflows, against a stub ``gh``
on PATH that records its calls.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
TAG = "v9.9.9"
VERSION = "9.9.9"

# Answers the few gh calls the release steps make. FAKE_IS_DRAFT and
# FAKE_ASSETS describe the release, FAKE_VIEW_ERROR makes `release view`
# fail, and FAKE_LATEST is the current latest release (none if unset).
FAKE_GH = r"""#!/bin/bash
printf '%s\n' "$*" >> "$GH_LOG"
if [ "$1" = "api" ]; then
  if [ -z "${FAKE_LATEST:-}" ]; then
    echo "HTTP 404: Not Found" >&2
    exit 1
  fi
  echo "$FAKE_LATEST"
elif [ "$1 $2" = "release view" ]; then
  if [ -n "${FAKE_VIEW_ERROR:-}" ]; then
    echo "$FAKE_VIEW_ERROR" >&2
    exit 1
  fi
  case "$*" in
    *"--json isDraft"*) echo "${FAKE_IS_DRAFT:-}" ;;
    *"--json assets"*) printf '%s\n' "${FAKE_ASSETS:-}" ;;
  esac
fi
exit 0
"""


@dataclass
class StepResult:
    returncode: int
    output: str
    gh_calls: list[str]

    def called(self, prefix: str) -> list[str]:
        return [call for call in self.gh_calls if call.startswith(prefix)]


RunStep = Callable[..., StepResult]


def _workflow(name: str) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    return data


def _job(workflow: str, job: str) -> dict[str, Any]:
    jobs: dict[str, dict[str, Any]] = _workflow(workflow)["jobs"]
    return jobs[job]


def _step(workflow: str, job: str, name: str) -> dict[str, Any]:
    return next(s for s in _job(workflow, job)["steps"] if s.get("name") == name)


def _steps(workflow: str) -> list[dict[str, Any]]:
    return [
        step
        for job in _workflow(workflow)["jobs"].values()
        for step in job.get("steps", [])
    ]


def _expected_assets() -> list[str]:
    """Every file a release ships, named the way install.sh and Imager fetch them."""
    wheels = [
        f"inkypi-wheels-{VERSION}-{arch}.tar.gz{suffix}"
        for arch in ("linux_armv7l", "linux_aarch64")
        for suffix in ("", ".sha256", ".manifest.sha256")
    ]
    image = f"inkypi-{VERSION}-pi-zero-2-w.img.xz"
    return [
        f"inkypi-{TAG}-bom.json",
        *wheels,
        image,
        f"{image}.sha256",
        f"inkypi-{VERSION}-os-list.json",
    ]


@pytest.fixture
def run_step(tmp_path: Path) -> RunStep:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()

    def run(
        step: dict[str, Any],
        job: dict[str, Any] | None = None,
        cwd: Path | None = None,
        **env: str,
    ) -> StepResult:
        declared = {**(job or {}).get("env", {}), **step.get("env", {})}
        workflow_env = {k: v for k, v in env.items() if not k.startswith("FAKE_")}
        undeclared = set(workflow_env) - set(declared)
        assert not undeclared, f"the step doesn't set {sorted(undeclared)}"
        log.write_text("")
        result = subprocess.run(
            # GitHub runs a `run:` script with `bash -e`.
            ["bash", "-e", "-c", step["run"]],
            cwd=cwd or tmp_path,
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "HOME": str(tmp_path),
                "GH_LOG": str(log),
                "RUNNER_TEMP": str(runner_temp),
                **env,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        return StepResult(
            result.returncode,
            result.stdout + result.stderr,
            log.read_text().splitlines(),
        )

    return run


# ---- semantic-release: the push goes over the deploy key ----


def test_release_job_pushes_with_the_deploy_key() -> None:
    job = _job("release.yml", "release")
    checkout = job["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["ssh-key"] == "${{ secrets.RELEASE_DEPLOY_KEY }}"
    # The key must stay configured for semantic-release's push.
    assert checkout["with"].get("persist-credentials", True) is not False
    # Its GITHUB_TOKEN can't push, so nothing here pushes any other way.
    assert job["permissions"] == {"contents": "read"}


def test_semantic_release_tags_without_creating_the_release() -> None:
    step = _step(
        "release.yml", "release", "Semantic Release — bump, commit, tag and push"
    )
    assert step["run"].strip() == "semantic-release version --no-vcs-release"
    assert "GH_TOKEN" not in step.get("env", {})
    workflow = (WORKFLOWS / "release.yml").read_text()
    assert "semantic-release publish" not in workflow
    # The draft takes the notes semantic-release would have posted.
    job = _job("release.yml", "release")
    assert job["outputs"]["notes"] == "${{ steps.psr.outputs.release_notes }}"


def test_semantic_release_config_pushes_without_a_token() -> None:
    config = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"][
        "semantic_release"
    ]
    assert config["remote"]["ignore_token_for_push"] is True
    # A deploy-key push starts workflows, unlike a GITHUB_TOKEN one. Keep the
    # version-only commit from running CI and another Release.
    subject, _, body = config["commit_message"].partition("\n")
    assert subject == "{version}"
    assert "[skip ci]" in body


def test_deploy_key_is_never_in_a_script() -> None:
    for workflow in ("release.yml", "build-wheelhouse.yml", "build-pi-image.yml"):
        for step in _steps(workflow):
            assert "secrets.RELEASE_DEPLOY_KEY" not in step.get("run", ""), step


@pytest.mark.parametrize(
    ("has_key", "origin", "ok"),
    [
        ("true", "git@github.com:jtn0123/InkyPi.git", True),
        ("false", "git@github.com:jtn0123/InkyPi.git", False),
        ("true", "https://github.com/jtn0123/InkyPi", False),
    ],
)
def test_release_stops_before_pushing_without_the_deploy_key(
    run_step: RunStep, tmp_path: Path, has_key: str, origin: str, ok: bool
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=repo, check=True)
    step = _step("release.yml", "release", "Confirm the push will use the deploy key")
    result = run_step(step, cwd=repo, HAS_DEPLOY_KEY=has_key)
    assert (result.returncode == 0) is ok, result.output


# ---- the release is created as a draft ----


def test_only_the_draft_job_creates_the_release() -> None:
    creators = {
        name
        for name, job in _workflow("release.yml")["jobs"].items()
        for step in job.get("steps", [])
        if "gh release create" in step.get("run", "")
    }
    assert creators == {"draft"}
    step = _job("release.yml", "draft")["steps"][0]
    create = next(
        line for line in step["run"].splitlines() if "gh release create" in line
    )
    assert "--draft" in create
    assert "--verify-tag" in create


def _draft_step() -> dict[str, Any]:
    return _step(
        "release.yml", "draft", "Create the draft, or refresh its notes on a re-run"
    )


def _draft_env(**extra: str) -> dict[str, str]:
    return {
        "GH_TOKEN": "token",
        "REPO": "jtn0123/InkyPi",
        "TAG": TAG,
        "NOTES": "# v9.9.9\n\n## Fix\n- a fix",
        **extra,
    }


def test_draft_step_creates_a_draft(run_step: RunStep, tmp_path: Path) -> None:
    result = run_step(_draft_step(), **_draft_env(FAKE_VIEW_ERROR="release not found"))
    assert result.returncode == 0, result.output
    (create,) = result.called("release create")
    assert create.startswith(f"release create {TAG} --repo jtn0123/InkyPi --draft")
    notes = (tmp_path / "runner-temp" / "release-notes.md").read_text()
    assert notes == "# v9.9.9\n\n## Fix\n- a fix\n"


def test_draft_step_rerun_refreshes_the_existing_draft(run_step: RunStep) -> None:
    result = run_step(_draft_step(), **_draft_env(FAKE_IS_DRAFT="true"))
    assert result.returncode == 0, result.output
    assert not result.called("release create")
    (edit,) = result.called("release edit")
    assert "--notes-file" in edit
    assert "--draft" not in edit


@pytest.mark.parametrize(
    "fake",
    [
        # Already published: its files can't change any more.
        {"FAKE_IS_DRAFT": "false"},
        # Any error but "not found" may hide an existing draft, and GitHub
        # allows two drafts for one tag.
        {"FAKE_VIEW_ERROR": "HTTP 502: Bad Gateway"},
        # No notes means semantic-release changed its output.
        {"FAKE_VIEW_ERROR": "release not found", "NOTES": ""},
    ],
)
def test_draft_step_fails_without_touching_the_release(
    run_step: RunStep, fake: dict[str, str]
) -> None:
    result = run_step(_draft_step(), **_draft_env(**fake))
    assert result.returncode != 0
    assert not result.called("release create")
    assert not result.called("release edit")


# ---- files are attached only to the draft ----

UPLOAD_STEPS = [
    ("release.yml", "sbom", "Attach SBOM to the draft release"),
    ("build-wheelhouse.yml", "build-wheels", "Attach wheelhouse to the draft release"),
    ("build-pi-image.yml", "attach-release", "Attach to the draft release"),
]


def _upload_env(workflow: str, event: str, **fake: str) -> dict[str, str]:
    env = {"GH_TOKEN": "token", "REPO": "jtn0123/InkyPi", "TAG": TAG, **fake}
    if workflow == "build-wheelhouse.yml":
        env |= {
            "EVENT": event,
            "TARBALL": f"inkypi-wheels-{VERSION}-linux_armv7l.tar.gz",
        }
    elif workflow == "build-pi-image.yml":
        image = f"inkypi-{VERSION}-pi-zero-2-w.img.xz"
        env |= {"EVENT": event, "VERSION": VERSION, "IMAGE": image}
    return env


@pytest.fixture
def sbom_dir(tmp_path: Path) -> Path:
    # The SBOM step copies the generated file before uploading it.
    (tmp_path / "artifacts" / "security").mkdir(parents=True)
    (tmp_path / "artifacts" / "security" / "sbom.json").write_text("{}")
    return tmp_path


def test_every_upload_checks_for_a_draft_and_replaces_files() -> None:
    uploads = [
        (workflow, step)
        for workflow in ("release.yml", "build-wheelhouse.yml", "build-pi-image.yml")
        for step in _steps(workflow)
        if "gh release upload" in step.get("run", "")
    ]
    assert {(w, s["name"]) for w, s in uploads} == {(w, n) for w, _, n in UPLOAD_STEPS}
    for _, step in uploads:
        assert "--json isDraft" in step["run"]
        assert "--clobber" in step["run"]


def test_no_workflow_uploads_with_softprops() -> None:
    # softprops/action-gh-release publishes a draft after uploading to it.
    for workflow in ("release.yml", "build-wheelhouse.yml", "build-pi-image.yml"):
        for step in _steps(workflow):
            assert "softprops/action-gh-release" not in step.get("uses", "")


@pytest.mark.parametrize("workflow", ["build-wheelhouse.yml", "build-pi-image.yml"])
def test_asset_workflows_do_not_run_on_publish(workflow: str) -> None:
    # A `release: published` run could only upload after the files are fixed.
    triggers = _workflow(workflow)[True]
    assert set(triggers) == {"workflow_call", "workflow_dispatch"}


# release.yml has no manual trigger; the reusable workflows run from it (where
# `github.event_name` is the caller's, workflow_run) or by hand.
UPLOAD_EVENTS = [
    (*upload, event)
    for upload in UPLOAD_STEPS
    for event in ("workflow_run", "workflow_dispatch")
    if upload[0] != "release.yml" or event == "workflow_run"
]


@pytest.mark.parametrize(("workflow", "job", "name", "event"), UPLOAD_EVENTS)
def test_upload_attaches_to_a_draft(
    run_step: RunStep,
    sbom_dir: Path,
    workflow: str,
    job: str,
    name: str,
    event: str,
) -> None:
    step = _step(workflow, job, name)
    result = run_step(
        step, cwd=sbom_dir, **_upload_env(workflow, event, FAKE_IS_DRAFT="true")
    )
    assert result.returncode == 0, result.output
    (upload,) = result.called("release upload")
    assert upload.startswith(f"release upload {TAG} ")
    assert "--clobber" in upload


@pytest.mark.parametrize(("workflow", "job", "name"), UPLOAD_STEPS)
@pytest.mark.parametrize(
    "fake",
    [{"FAKE_IS_DRAFT": "false"}, {"FAKE_VIEW_ERROR": "release not found"}],
)
def test_release_run_fails_rather_than_upload_to_a_published_release(
    run_step: RunStep,
    sbom_dir: Path,
    workflow: str,
    job: str,
    name: str,
    fake: dict[str, str],
) -> None:
    step = _step(workflow, job, name)
    result = run_step(
        step, cwd=sbom_dir, **_upload_env(workflow, "workflow_run", **fake)
    )
    assert result.returncode != 0
    assert not result.called("release upload")


@pytest.mark.parametrize(("workflow", "job", "name"), UPLOAD_STEPS[1:])
@pytest.mark.parametrize(
    "fake",
    [{"FAKE_IS_DRAFT": "false"}, {"FAKE_VIEW_ERROR": "release not found"}],
)
def test_manual_recheck_keeps_the_build_as_an_artifact(
    run_step: RunStep, workflow: str, job: str, name: str, fake: dict[str, str]
) -> None:
    step = _step(workflow, job, name)
    result = run_step(step, **_upload_env(workflow, "workflow_dispatch", **fake))
    assert result.returncode == 0, result.output
    assert not result.called("release upload")
    assert "::notice" in result.output
    uploads_artifact = any(
        "actions/upload-artifact@" in s.get("uses", "") for s in _steps(workflow)
    )
    assert uploads_artifact


def test_wheelhouse_artifact_holds_every_wheelhouse_file() -> None:
    step = _step(
        "build-wheelhouse.yml",
        "build-wheels",
        "Keep the wheelhouse as a workflow artifact",
    )
    paths = step["with"]["path"].splitlines()
    tarball = "${{ steps.package.outputs.tarball }}"
    assert paths == [tarball, f"{tarball}.sha256", f"{tarball}.manifest.sha256"]
    assert step["with"]["if-no-files-found"] == "error"


@pytest.mark.parametrize("workflow", ["build-wheelhouse.yml", "build-pi-image.yml"])
def test_artifact_uploads_survive_rerunning_a_failed_job(workflow: str) -> None:
    # Re-running failed jobs is how a stuck draft is finished, and an artifact
    # name already used in the run would fail the re-run.
    uploads = [
        step
        for step in _steps(workflow)
        if "actions/upload-artifact@" in step.get("uses", "")
    ]
    assert uploads
    for step in uploads:
        assert step["with"].get("overwrite") is True, step["name"]


def test_pi_image_reuse_run_never_attaches() -> None:
    # A reuse_run_id run skips build-image; the attach job needs it to pass.
    job = _job("build-pi-image.yml", "attach-release")
    assert job["needs"] == ["build-image", "verify-boot"]
    assert job["if"] == "needs.verify-boot.outputs.verified == 'true'"
    assert "always()" not in job["if"]


# ---- publish comes last, and only after every asset job ----


def test_publish_needs_every_asset_job() -> None:
    jobs = _workflow("release.yml")["jobs"]
    asset_jobs = {
        name for name, job in jobs.items() if "draft" in (job.get("needs") or [])
    }
    assert asset_jobs == {"sbom", "wheelhouse", "pi-image", "publish"}
    publish = jobs["publish"]
    assert set(publish["needs"]) == {
        "release",
        "draft",
        "sbom",
        "wheelhouse",
        "pi-image",
    }
    # A status function would let it run after a failed or skipped asset job.
    for function in ("always()", "failure()", "cancelled()", "success()"):
        assert function not in publish["if"]


def test_nothing_runs_after_publish() -> None:
    jobs = _workflow("release.yml")["jobs"]
    for name, job in jobs.items():
        needs = job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        assert "publish" not in needs, name
    publishing = [
        (name, step["name"])
        for name, job in jobs.items()
        for step in job.get("steps", [])
        if "--draft=false" in step.get("run", "")
    ]
    assert publishing == [("publish", jobs["publish"]["steps"][-1]["name"])]


def _publish_job() -> dict[str, Any]:
    return _job("release.yml", "publish")


def _publish_env(**fake: str) -> dict[str, str]:
    return {"GH_TOKEN": "token", "REPO": "jtn0123/InkyPi", "TAG": TAG, **fake}


def test_publish_checks_for_every_file(run_step: RunStep) -> None:
    job = _publish_job()
    check = _step("release.yml", "publish", "Check every file is on the draft")
    complete = "\n".join(_expected_assets())
    result = run_step(check, job, **_publish_env(FAKE_ASSETS=complete))
    assert result.returncode == 0, result.output
    for missing in _expected_assets():
        rest = "\n".join(a for a in _expected_assets() if a != missing)
        result = run_step(check, job, **_publish_env(FAKE_ASSETS=rest))
        assert result.returncode != 0, missing
        assert missing in result.output


def test_publish_expects_each_wheelhouse_architecture() -> None:
    matrix = _job("build-wheelhouse.yml", "build-wheels")["strategy"]["matrix"]
    check = _step("release.yml", "publish", "Check every file is on the draft")
    for arch in (entry["arch"] for entry in matrix["include"]):
        assert f'"inkypi-wheels-${{VERSION}}-{arch}.tar.gz"' in check["run"]


@pytest.mark.parametrize(
    ("latest", "make_latest"),
    [("v9.9.8", "true"), ("", "true"), ("v9.10.0", "false")],
)
def test_publish_marks_the_release_latest_unless_a_newer_one_is(
    run_step: RunStep, latest: str, make_latest: str
) -> None:
    step = _step("release.yml", "publish", "Publish the draft")
    result = run_step(
        step, _publish_job(), **_publish_env(FAKE_IS_DRAFT="true", FAKE_LATEST=latest)
    )
    assert result.returncode == 0, result.output
    (edit,) = result.called("release edit")
    assert edit == (
        f"release edit {TAG} --repo jtn0123/InkyPi --draft=false --latest={make_latest}"
    )


def test_publish_rerun_after_publishing_changes_nothing(run_step: RunStep) -> None:
    step = _step("release.yml", "publish", "Publish the draft")
    result = run_step(step, _publish_job(), **_publish_env(FAKE_IS_DRAFT="false"))
    assert result.returncode == 0, result.output
    assert not result.called("release edit")

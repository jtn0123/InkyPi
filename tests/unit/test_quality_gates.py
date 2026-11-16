"""Regression tests for CI quality gate wiring."""

from pathlib import Path

from scripts import mutation_check

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_narrow_mutation_targets_exist_and_match_snippets() -> None:
    """The narrow mutation harness must not drift after source moves."""
    for mutant in mutation_check.MUTANTS:
        target = REPO_ROOT / mutant.file
        assert target.exists(), f"{mutant.name} target is missing: {mutant.file}"
        assert mutant.old in target.read_text(
            encoding="utf-8"
        ), f"{mutant.name} snippet is missing from {mutant.file}"


def test_pr_benchmark_gate_uploads_auditable_artifacts() -> None:
    """Benchmark runs should leave the numbers and the comparison behind."""
    ci_yaml = CI_YAML.read_text(encoding="utf-8")
    assert "Upload benchmark artifacts" in ci_yaml
    assert "path: /tmp/bench/" in ci_yaml
    assert "| tee /tmp/bench/compare.txt" in ci_yaml


def test_benchmark_gate_times_the_base_commit_on_the_same_runner() -> None:
    """A baseline from another runner made unrelated PRs fail by 25-33%."""
    ci_yaml = CI_YAML.read_text(encoding="utf-8")
    lint_job = ci_yaml[ci_yaml.index("  lint:\n") : ci_yaml.index("  lockfile-drift:")]
    # HEAD^1 (the PR's base) is only in the checkout with fetch-depth 2.
    assert "fetch-depth: 2" in lint_job
    assert "git worktree add --detach /tmp/bench-base HEAD^1" in lint_job
    assert "--baseline /tmp/bench/base-1.json /tmp/bench/base-2.json" in lint_job
    assert "--current /tmp/bench/current-1.json /tmp/bench/current-2.json" in lint_job
    assert "benchmark-baseline-" not in ci_yaml  # no cached baseline
    assert "|| true" not in lint_job.split("Run perf benchmarks", 1)[1]

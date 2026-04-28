"""Regression tests for CI quality gate wiring."""

from pathlib import Path

from scripts import mutation_check

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_narrow_mutation_targets_exist_and_match_snippets():
    """The narrow mutation harness must not drift after source moves."""
    for mutant in mutation_check.MUTANTS:
        target = REPO_ROOT / mutant.file
        assert target.exists(), f"{mutant.name} target is missing: {mutant.file}"
        assert mutant.old in target.read_text(
            encoding="utf-8"
        ), f"{mutant.name} snippet is missing from {mutant.file}"


def test_pr_benchmark_gate_uploads_auditable_artifacts():
    """PR benchmark runs should leave numbers and comparison logs behind."""
    ci_yaml = CI_YAML.read_text(encoding="utf-8")
    assert "Upload benchmark artifacts" in ci_yaml
    assert "/tmp/bench-current.json" in ci_yaml
    assert "/tmp/benchmark-compare.txt" in ci_yaml
    assert "/tmp/bench-effective-baseline.json" in ci_yaml


def test_pr_benchmark_repo_baseline_fallback_is_blocking():
    """A missing CI cache must not turn benchmark regressions advisory-only."""
    ci_yaml = CI_YAML.read_text(encoding="utf-8")
    assert "informational only" not in ci_yaml
    assert (
        "cp tests/benchmarks/baseline.json /tmp/bench-effective-baseline.json"
        in ci_yaml
    )
    assert "--baseline /tmp/bench-effective-baseline.json" in ci_yaml
    assert "--current /tmp/bench-current.json || true" not in ci_yaml

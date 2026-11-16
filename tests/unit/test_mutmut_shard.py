"""Tests for scripts/mutmut_shard.py: the nightly's shards and their resume."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml
from scripts import mutmut_shard
from scripts.mutation_summary import load_floors

ROOT = Path(__file__).resolve().parents[2]


def _only_mutate() -> list[str]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        patterns = tomllib.load(fh)["tool"]["mutmut"]["only_mutate"]
    assert isinstance(patterns, list)
    return [str(p) for p in patterns]


def _matrix_labels() -> list[str]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    include = workflow["jobs"]["mutation-nightly"]["strategy"]["matrix"]["include"]
    return [str(entry["label"]) for entry in include]


def test_shards_split_the_mutation_scope_exactly() -> None:
    sharded = [p for patterns in mutmut_shard.SHARDS.values() for p in patterns]
    assert len(sharded) == len(set(sharded)), "a pattern belongs to two shards"
    assert set(sharded) == set(_only_mutate())


def test_ci_matrix_runs_every_shard() -> None:
    assert _matrix_labels() == list(mutmut_shard.SHARDS)


def test_every_shard_has_a_score_entry() -> None:
    allowed_drop, floors = load_floors(ROOT / "scripts/mutation_scores.json")
    assert allowed_drop == 2.0
    assert set(floors) == set(mutmut_shard.SHARDS)


def test_nightly_resumes_through_the_wrapper_with_a_weekly_cache() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["mutation-nightly"]["steps"]
    by_name = {step.get("name"): step for step in steps}
    run = by_name["Run mutmut"]["run"]
    # Named mutants are re-tested even when they have a result, so the run
    # must go through the wrapper with no names.
    assert 'python scripts/mutmut_shard.py "$LABEL" run --max-children 2' in run
    assert "mutmut run" not in run
    key_step = by_name["Pick the mutation cache key"]["run"]
    assert "date -u +%G-W%V" in key_step
    assert 'm.version("mutmut")' in key_step
    restore = by_name["Restore this week's mutation results"]["with"]
    save = by_name["Save this week's mutation results"]["with"]
    assert restore["path"] == save["path"] == "mutants/**/*.meta"
    assert restore["key"] == save["key"]
    assert restore["restore-keys"] == "${{ steps.mutation-cache.outputs.prefix }}"
    check = by_name["Compare with the committed mutation score"]["run"]
    assert "--floors scripts/mutation_scores.json --check" in check
    assert "if" not in by_name["Compare with the committed mutation score"]


def test_narrow_scope_limits_mutmut_to_the_shard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mutmut.configuration import _load_config

    # A fresh Config: the nightly runs this test inside mutmut's own process,
    # so the global mutmut config must not be touched.
    monkeypatch.chdir(ROOT)
    cfg = _load_config()
    mutmut_shard.narrow_scope("core", cfg)
    assert cfg.only_mutate == ["src/config.py", "src/model.py", "src/services/*"]
    assert cfg.should_mutate("src/config.py")
    assert cfg.should_mutate("src/services/history.py")
    assert not cfg.should_mutate("src/blueprints/main.py")
    assert not cfg.should_mutate("src/utils/time_utils.py")


def test_narrow_scope_refuses_a_shard_outside_only_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mutmut.configuration import _load_config

    monkeypatch.chdir(ROOT)
    cfg = _load_config()
    cfg.only_mutate = ["src/blueprints/*"]
    with pytest.raises(SystemExit, match="does not list"):
        mutmut_shard.narrow_scope("utils", cfg)


def _write_meta(path: Path, exit_codes: dict[str, int | None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "exit_code_by_key": exit_codes,
                "hash_by_function_name": {},
                "type_check_error_by_key": {},
                "durations_by_key": {},
                "estimated_durations_by_key": {},
            }
        ),
        encoding="utf-8",
    )


def test_prepare_restored_results_keeps_results_and_requeues_interrupted(
    tmp_path: Path,
) -> None:
    good = tmp_path / "src/utils/a.py.meta"
    _write_meta(good, {"a__mutmut_1": 1, "a__mutmut_2": 0, "a__mutmut_3": 2})
    untouched = tmp_path / "src/utils/b.py.meta"
    _write_meta(untouched, {"b__mutmut_1": None, "b__mutmut_2": 33})
    before = untouched.read_text(encoding="utf-8")
    truncated = tmp_path / "src/utils/c.py.meta"
    truncated.write_text('{"exit_code_by_key": {"c__mut', encoding="utf-8")
    wrong_shape = tmp_path / "src/utils/d.py.meta"
    wrong_shape.write_text("[1, 2]", encoding="utf-8")

    restored = mutmut_shard.prepare_restored_results(tmp_path)

    assert restored == mutmut_shard.RestoredResults(
        results=3, requeued=1, dropped_files=2
    )
    assert not truncated.exists()
    assert not wrong_shape.exists()
    codes = json.loads(good.read_text(encoding="utf-8"))["exit_code_by_key"]
    assert codes == {"a__mutmut_1": 1, "a__mutmut_2": 0, "a__mutmut_3": None}
    assert untouched.read_text(encoding="utf-8") == before


def test_prepare_restored_results_without_a_tree(tmp_path: Path) -> None:
    restored = mutmut_shard.prepare_restored_results(tmp_path / "mutants")
    assert restored == mutmut_shard.RestoredResults(0, 0, 0)


@pytest.mark.parametrize(
    "argv", [[], ["blueprints"], ["no-such-shard", "run"], ["run", "blueprints"]]
)
def test_main_rejects_bad_arguments(argv: list[str]) -> None:
    assert mutmut_shard.main(argv) == 2

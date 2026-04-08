"""Tests that mutmut configuration is present and well-formed.

This ensures future PRs cannot accidentally remove or corrupt the mutation
testing config without a test failure drawing attention to the change.
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

EXPECTED_FILES = [
    "src/utils/http_utils.py",
    "src/utils/image_serving.py",
    "src/refresh_task/task.py",
]


def _load_mutmut_config() -> dict:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tool", {}).get("mutmut", {})


class TestMutmutConfig:
    def test_section_exists(self):
        cfg = _load_mutmut_config()
        assert cfg, "[tool.mutmut] section is missing from pyproject.toml"

    def test_paths_to_mutate_present(self):
        cfg = _load_mutmut_config()
        assert (
            "paths_to_mutate" in cfg
        ), "paths_to_mutate key missing from [tool.mutmut]"

    def test_paths_to_mutate_not_empty(self):
        cfg = _load_mutmut_config()
        paths = cfg.get("paths_to_mutate", "")
        assert paths.strip(), "paths_to_mutate must not be empty"

    def test_expected_files_in_scope(self):
        cfg = _load_mutmut_config()
        paths = cfg.get("paths_to_mutate", "")
        for expected in EXPECTED_FILES:
            assert expected in paths, (
                f"{expected} is not in paths_to_mutate — "
                "do not remove files from mutation scope without a deliberate decision"
            )

    def test_tests_dir_configured(self):
        cfg = _load_mutmut_config()
        assert (
            cfg.get("tests_dir") == "tests/"
        ), "tests_dir should be 'tests/' in [tool.mutmut]"

    def test_runner_configured(self):
        cfg = _load_mutmut_config()
        runner = cfg.get("runner", "")
        assert "pytest" in runner, "runner should invoke pytest"

    def test_scoped_files_exist_on_disk(self):
        root = PYPROJECT.parent
        cfg = _load_mutmut_config()
        paths = cfg.get("paths_to_mutate", "")
        for rel_path in [p.strip() for p in paths.split(",") if p.strip()]:
            full = root / rel_path
            assert full.exists(), (
                f"Mutation scope references {rel_path} but file does not exist. "
                "Either create the file or remove it from paths_to_mutate."
            )

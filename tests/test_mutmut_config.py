"""Tests that mutmut configuration is present and well-formed.

This ensures future PRs cannot accidentally remove or corrupt the mutation
testing config without a test failure drawing attention to the change.
"""

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

EXPECTED_FILES = [
    "src/app_setup/",
    "src/blueprints/",
    "src/utils/",
    "src/refresh_task/",
]


def _load_mutmut_config() -> dict:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tool", {}).get("mutmut", {})


class TestMutmutConfig:
    def test_section_exists(self) -> None:
        cfg = _load_mutmut_config()
        assert cfg, "[tool.mutmut] section is missing from pyproject.toml"

    def test_source_paths_present(self) -> None:
        cfg = _load_mutmut_config()
        assert "source_paths" in cfg, "source_paths key missing from [tool.mutmut]"

    def test_source_tree_available(self) -> None:
        cfg = _load_mutmut_config()
        assert cfg.get("source_paths") == ["src/"]

    def test_expected_files_in_scope(self) -> None:
        cfg = _load_mutmut_config()
        configured = set(cfg.get("only_mutate", []))
        for expected in EXPECTED_FILES:
            assert expected + "*" in configured, (
                f"{expected} is not in only_mutate — "
                "do not remove files from mutation scope without a deliberate decision"
            )

    def test_tests_dir_configured(self) -> None:
        cfg = _load_mutmut_config()
        assert cfg.get("pytest_add_cli_args_test_selection") == [
            "tests/"
        ], "mutmut must run the project tests"

    def test_installed_mutmut_accepts_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mutmut.configuration import _load_config

        monkeypatch.chdir(PYPROJECT.parent)
        cfg = _load_config()
        assert cfg.pytest_add_cli_args_test_selection == ["tests/"]
        for expected in EXPECTED_FILES:
            assert cfg.should_mutate(expected + "example.py")
        assert not cfg.should_mutate("src/plugins/clock/clock.py")

    def test_scoped_files_exist_on_disk(self) -> None:
        root = PYPROJECT.parent
        cfg = _load_mutmut_config()
        for rel_path in cfg.get("source_paths", []):
            full = root / rel_path
            assert full.exists(), (
                f"Mutation scope references {rel_path} but file does not exist. "
                "Either create the file or remove it from source_paths."
            )
            if rel_path.endswith("/"):
                assert full.is_dir(), f"{rel_path} should be a directory path"
            else:
                assert full.is_file(), f"{rel_path} should be a file path"

"""Unit tests for install/_preflight.py — the updater's pre-flight gates (B4).

The helper is invoked by do_update.sh before ``git checkout`` and by update.sh
before the service is stopped. These tests drive it in-process against a
throwaway repo tree; the shell wiring is covered by
tests/integration/test_update_preflight_gates.py.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "install" / "_preflight.py"


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_inkypi_preflight", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pf = _load_helper()


def _make_repo(
    root: Path,
    *,
    config: dict[str, Any] | None = None,
    version: str | None = "1.2.3\n",
    drivers: tuple[str, ...] = (),
    manifest: tuple[str, ...] = ("epd7in3e.py",),
) -> Path:
    (root / "install").mkdir(parents=True)
    rows = [f"{name} {'a' * 40} {'b' * 64}" for name in (*manifest, "epdconfig.py")]
    (root / "install" / "waveshare-manifest.txt").write_text(
        "# Format: <driver_name> <commit_sha> <sha256>\n" + "\n".join(rows) + "\n"
    )
    if version is not None:
        (root / "VERSION").write_text(version)
    if config is not None:
        (root / "src" / "config").mkdir(parents=True)
        (root / "src" / "config" / "device.json").write_text(json.dumps(config))
    driver_dir = root / "src" / "display" / "waveshare_epd"
    driver_dir.mkdir(parents=True)
    for name in drivers:
        (driver_dir / name).write_text("# driver\n")
    return root


def _run(
    repo: Path, *extra: str, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    rc = pf.main(["--repo-dir", str(repo), "--min-free-mb", "1", *extra])
    out, err = capsys.readouterr()
    return rc, out, err


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INKYPI_UPDATE_MIN_FREE_MB", raising=False)
    monkeypatch.delenv("INKYPI_CONFIG_FILE", raising=False)


class TestAllGatesPass:
    def test_mock_display_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path / "repo", config={"display_type": "mock"})
        rc, out, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_OK, err
        assert "PREFLIGHT FAIL" not in err
        for gate in ("disk", "version", "config", "display"):
            assert f"preflight {gate}: ok" in out

    def test_no_config_yet_skips_config_and_display(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path / "repo", config=None)
        rc, out, _ = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_OK
        assert "preflight config: skipped" in out

    def test_waveshare_with_pinned_driver_present_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(
            tmp_path / "repo",
            config={"display_type": "epd7in3e"},
            drivers=("epd7in3e.py", "epdconfig.py"),
        )
        rc, out, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_OK, err
        assert "display epd7in3e (driver present)" in out


class TestDiskGate:
    def test_below_threshold_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path / "repo", config={"display_type": "mock"})
        rc = pf.main(["--repo-dir", str(repo), "--min-free-mb", str(10**12)])
        err = capsys.readouterr().err
        assert rc == pf.EXIT_FAILED
        assert "PREFLIGHT FAIL: only" in err
        assert "INKYPI_UPDATE_MIN_FREE_MB" in err

    def test_env_var_sets_threshold(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _make_repo(tmp_path / "repo", config={"display_type": "mock"})
        monkeypatch.setenv("INKYPI_UPDATE_MIN_FREE_MB", str(10**12))
        assert pf.main(["--repo-dir", str(repo)]) == pf.EXIT_FAILED
        assert "PREFLIGHT FAIL: only" in capsys.readouterr().err

    def test_zero_disables(self, tmp_path: Path) -> None:
        assert pf.check_disk_space([tmp_path], 0) == "disk space check disabled"

    def test_non_numeric_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INKYPI_UPDATE_MIN_FREE_MB", "lots")
        assert pf._min_free_mb_default() == pf.DEFAULT_MIN_FREE_MB

    def test_missing_path_checks_nearest_existing_ancestor(
        self, tmp_path: Path
    ) -> None:
        report = pf.check_disk_space([tmp_path / "not" / "yet" / "created"], 1)
        assert "MB free" in report

    def test_same_filesystem_reported_once(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert pf.check_disk_space([a, b], 1).count("MB free") == 1


class TestVersionGate:
    @pytest.mark.parametrize("content", ["", "  \n\n"])
    def test_empty_version_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
    ) -> None:
        repo = _make_repo(tmp_path / "repo", version=content)
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "VERSION is empty" in err

    def test_missing_version_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path / "repo", version=None)
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "VERSION is unreadable" in err

    def test_stdin_version(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _make_repo(tmp_path / "repo", version=None)
        monkeypatch.setattr("sys.stdin", io.StringIO("2.0.0\n"))
        rc, out, err = _run(repo, "--version-file", "-", capsys=capsys)
        assert rc == pf.EXIT_OK, err
        assert "version 2.0.0" in out

    def test_empty_stdin_names_target(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _make_repo(tmp_path / "repo")
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        rc, _, err = _run(repo, "--version-file", "-", capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "PREFLIGHT FAIL: target VERSION is empty or missing" in err


class TestConfigGate:
    def test_schema_violation_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(
            tmp_path / "repo",
            config={"display_type": "mock", "orientation": "sideways"},
        )
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "failed schema validation" in err
        assert "orientation" in err

    def test_invalid_json_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path / "repo", config={})
        (repo / "src" / "config" / "device.json").write_text("{not json")
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "is not valid JSON" in err

    def test_non_object_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path / "repo", config={})
        (repo / "src" / "config" / "device.json").write_text("[]")
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "must contain a JSON object" in err

    def test_inkypi_config_file_env_is_honoured(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _make_repo(tmp_path / "repo", config={"display_type": "mock"})
        bad = tmp_path / "elsewhere.json"
        bad.write_text(json.dumps({"orientation": "diagonal"}))
        monkeypatch.setenv("INKYPI_CONFIG_FILE", str(bad))
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert str(bad) in err

    def test_falls_back_to_device_dev_json(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        (repo / "src" / "config").mkdir(parents=True)
        dev = repo / "src" / "config" / "device_dev.json"
        dev.write_text("{}")
        assert pf.resolve_config_path(repo, None) == dev

    def test_display_not_checked_when_config_invalid(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(
            tmp_path / "repo",
            config={"display_type": "epd7in3e", "orientation": "sideways"},
        )
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert err.count("PREFLIGHT FAIL") == 1


class TestDisplayGate:
    def test_missing_waveshare_driver_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(
            tmp_path / "repo",
            config={"display_type": "epd7in3e"},
            drivers=("epdconfig.py",),
        )
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "epd7in3e.py is missing" in err
        assert "install.sh -W epd7in3e" in err

    def test_missing_epdconfig_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(
            tmp_path / "repo",
            config={"display_type": "epd7in3e"},
            drivers=("epd7in3e.py",),
        )
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "epdconfig.py is missing" in err

    def test_unpinned_waveshare_driver_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(
            tmp_path / "repo",
            config={"display_type": "epd2in13"},
            drivers=("epd2in13.py", "epdconfig.py"),
        )
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "not pinned" in err

    def test_inky_requires_package(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _make_repo(tmp_path / "repo", config={"display_type": "inky"})
        monkeypatch.setattr(pf.importlib.util, "find_spec", lambda name: None)
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        assert "inky package is not importable" in err

    def test_inky_package_present_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pf.importlib.util, "find_spec", lambda name: object())
        assert "inky package present" in pf.check_display_driver(
            tmp_path, {"display_type": "inky"}
        )

    def test_absent_display_type_defaults_to_inky(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        def fake_find_spec(name: str) -> object:
            seen.append(name)
            return object()

        monkeypatch.setattr(pf.importlib.util, "find_spec", fake_find_spec)
        pf.check_display_driver(tmp_path, {})
        assert seen == ["inky"]

    @pytest.mark.parametrize("display_type", ["waveshare", "epd../../x"])
    def test_unsupported_display_type_fails(
        self, tmp_path: Path, display_type: str
    ) -> None:
        with pytest.raises(pf.PreflightError):
            pf.check_display_driver(tmp_path, {"display_type": display_type})


class TestFailureOutput:
    def test_reports_every_failure_on_its_own_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(
            tmp_path / "repo", version="", config={"display_type": "epd7in3e"}
        )
        rc, _, err = _run(repo, capsys=capsys)
        assert rc == pf.EXIT_FAILED
        lines = [ln for ln in err.splitlines() if ln.startswith("PREFLIGHT FAIL: ")]
        assert len(lines) == 2
        assert "VERSION" in lines[0]
        assert "epd7in3e" in lines[1]


def test_real_waveshare_display_type_passes_device_schema() -> None:
    """install.sh writes display_type=<driver name> (e.g. epd7in3e); the schema
    used to enum only mock/inky/waveshare, so every Waveshare device's config
    failed validation — which would make the config gate block every update."""
    from utils.config_schema import validate_device_config

    for display_type in ("mock", "inky", "epd7in3e", "epd13in3k", "epd2in13_V4"):
        validate_device_config({"display_type": display_type})


@pytest.mark.parametrize("display_type", ["waveshare", "epson", "epd7in3e;rm"])
def test_unsupported_display_type_fails_device_schema(display_type: str) -> None:
    """The schema accepts only what DisplayManager can actually drive."""
    from utils.config_schema import ConfigValidationError, validate_device_config

    with pytest.raises(ConfigValidationError):
        validate_device_config({"display_type": display_type})

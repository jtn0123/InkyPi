"""The service sandbox drop-in (E3) and the bytecode precompile that goes with it.

``install_hardening_dropin`` makes everything outside a short list of paths
read-only to inkypi.service. These tests run the real ``_common.sh`` functions
against a throwaway repo layout, and check that every place the app writes at
runtime is on the list, so a new write location can't silently land on a
read-only path.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL_DIR = ROOT / "install"
COMMON_SH = INSTALL_DIR / "_common.sh"


def _layout(tmp_path: Path, repo_name: str = "InkyPi") -> dict[str, Path]:
    base = tmp_path.resolve()
    repo = base / "home" / repo_name
    (repo / "install").mkdir(parents=True)
    (repo / "src").mkdir()
    return {
        "repo": repo,
        "install": base / "usr-local-inkypi",
        "venv": base / "usr-local-inkypi" / "venv_inkypi",
        "dropins": base / "inkypi.service.d",
        "home": base / "root",
        "state": base / "var-lib-inkypi",
    }


def _run(layout: dict[str, Path], function: str) -> str:
    env = {
        **os.environ,
        "INKYPI_DROPIN_DIR": str(layout["dropins"]),
        "INKYPI_SERVICE_HOME": str(layout["home"]),
        "INKYPI_LOCKFILE_DIR": str(layout["state"]),
    }
    script = (
        f'source "{COMMON_SH}"; '
        f'SCRIPT_DIR="{layout["repo"] / "install"}"; '
        f'INSTALL_PATH="{layout["install"]}"; '
        f'VENV_PATH="{layout["venv"]}"; '
        f"{function}"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=60,
    )
    return result.stdout + result.stderr


def _settings(dropin: Path) -> dict[str, str]:
    settings = {}
    for line in dropin.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            settings[key] = value
    return settings


def test_writes_the_sandbox_with_this_devices_paths(tmp_path: Path) -> None:
    layout = _layout(tmp_path)

    _run(layout, "install_hardening_dropin")

    settings = _settings(layout["dropins"] / "hardening.conf")
    assert settings["NoNewPrivileges"] == "yes"
    assert settings["ProtectSystem"] == "strict"
    assert settings["ProtectHome"] == "read-only"
    assert settings["PrivateTmp"] == "yes"
    repo, home = layout["repo"], layout["home"]
    assert settings["ReadWritePaths"].split() == [
        str(layout["install"]),
        str(repo / "src" / "config"),
        str(repo / "src" / "static" / "images"),
        str(repo / "runtime"),
        str(layout["state"]),
        str(home / ".cache"),
        str(home / ".config"),
        f"-{home / '.pki'}",
        f"-{home / '.local'}",
    ]
    assert settings["ReadOnlyPaths"] == str(layout["venv"])


def test_creates_every_required_path_so_the_unit_can_start(tmp_path: Path) -> None:
    # systemd refuses to start a unit whose ReadWritePaths= entry is missing.
    layout = _layout(tmp_path)

    _run(layout, "install_hardening_dropin")

    settings = _settings(layout["dropins"] / "hardening.conf")
    required = [p for p in settings["ReadWritePaths"].split() if p[0] != "-"]
    assert all(Path(p).is_dir() for p in required)
    assert (layout["home"] / ".cache").stat().st_mode & 0o777 == 0o700


def test_rewriting_it_is_idempotent(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    dropin = layout["dropins"] / "hardening.conf"

    _run(layout, "install_hardening_dropin")
    first = dropin.read_text(encoding="utf-8")
    _run(layout, "install_hardening_dropin")

    assert dropin.read_text(encoding="utf-8") == first


def test_skips_the_sandbox_for_a_path_systemd_would_misread(tmp_path: Path) -> None:
    # A space splits a ReadWritePaths= entry in two; a stale drop-in for the
    # old paths must not survive either.
    layout = _layout(tmp_path, repo_name="My InkyPi")
    layout["dropins"].mkdir()
    (layout["dropins"] / "hardening.conf").write_text("[Service]\n", encoding="utf-8")

    out = _run(layout, "install_hardening_dropin")

    assert "Skipping the service sandbox" in out
    assert not (layout["dropins"] / "hardening.conf").exists()


def _function_body(script: Path, name: str) -> str:
    text = script.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", text, re.MULTILINE | re.DOTALL)
    assert match, f"{name} not found in {script.name}"
    return match.group(1)


@pytest.mark.parametrize(
    ("script", "function"),
    [("install.sh", "install_app_service"), ("update.sh", "update_app_service")],
)
def test_installers_write_it_before_reloading_systemd(
    script: str, function: str
) -> None:
    body = _function_body(INSTALL_DIR / script, function)

    reload_at = body.index("systemctl daemon-reload")
    assert -1 < body.find("install_hardening_dropin") < reload_at
    assert -1 < body.find("precompile_app_bytecode") < reload_at


def _writable_dirs(tmp_path: Path) -> list[Path]:
    """The drop-in's writable paths, mapped from the test layout onto the real
    repo and the production install and state directories."""
    layout = _layout(tmp_path)
    _run(layout, "install_hardening_dropin")
    real = {
        layout["repo"]: ROOT,
        layout["install"]: Path("/usr/local/inkypi"),
        layout["state"]: Path("/var/lib/inkypi"),
    }
    dirs = []
    for entry in _settings(layout["dropins"] / "hardening.conf")[
        "ReadWritePaths"
    ].split():
        path = Path(entry.lstrip("-"))
        for fake, actual in real.items():
            if path.is_relative_to(fake):
                path = actual / path.relative_to(fake)
        dirs.append(path)
    return dirs


def test_every_runtime_write_location_is_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # utils.paths holds the defaults; Config's class attributes can be
    # reassigned at runtime (inkypi.py --config), so don't read those.
    from benchmarks.benchmark_storage import _get_db_path
    from blueprints.settings import _update_target_version_path
    from config import Config
    from utils import paths
    from utils.app_utils import resolve_path
    from utils.plugin_history import _history_dir

    monkeypatch.delenv("INKYPI_LOCKFILE_DIR", raising=False)
    monkeypatch.setenv("PROJECT_DIR", "/usr/local/inkypi")

    class _DefaultConfig:
        BASE_DIR = paths.BASE_DIR

        def get_config(self, _key: str, default: object = None) -> object:
            return default

    config_dir = os.path.join(paths.BASE_DIR, "config")
    written = {
        "device.json": os.path.join(config_dir, "device.json"),
        "plugin history": _history_dir(config_dir),
        "current image": paths.CURRENT_IMAGE_FILE,
        "processed image": paths.PROCESSED_IMAGE_FILE,
        "plugin images": paths.PLUGIN_IMAGE_DIR,
        "history images": paths.HISTORY_IMAGE_DIR,
        "uploads": resolve_path(os.path.join("static", "images", "saved")),
        "benchmarks.db": _get_db_path(_DefaultConfig()),
        "update target": _update_target_version_path(),
        ".env": Config.get_env_file_path(Config.__new__(Config)),
    }
    writable = _writable_dirs(tmp_path)

    outside = {
        name: path
        for name, path in written.items()
        if not any(Path(path).resolve().is_relative_to(d.resolve()) for d in writable)
    }
    assert not outside, f"the sandbox makes these read-only: {outside}"


def test_crash_breadcrumbs_use_the_units_runtime_directory() -> None:
    # /run/inkypi isn't in ReadWritePaths=: RuntimeDirectory= makes it writable.
    from utils import crash_breadcrumb

    unit = (INSTALL_DIR / "inkypi.service").read_text(encoding="utf-8")

    assert "RuntimeDirectory=inkypi" in unit
    assert crash_breadcrumb._DEFAULT_RUNTIME_DIR == "/run/inkypi"


def _python_stub(layout: dict[str, Path], exit_code: int) -> Path:
    log = layout["repo"].parent / "python.log"
    bin_dir = layout["venv"] / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "python"
    stub.write_text(
        f'#!/bin/bash\necho "$@" >> "{log}"\nexit {exit_code}\n', encoding="utf-8"
    )
    stub.chmod(0o755)
    return log


def test_precompile_compiles_src_with_the_venv_python(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    log = _python_stub(layout, exit_code=0)

    _run(layout, "precompile_app_bytecode")

    assert log.read_text(encoding="utf-8").split() == [
        "-m",
        "compileall",
        "-q",
        str(layout["repo"] / "src"),
    ]


def test_a_failed_precompile_only_warns(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _python_stub(layout, exit_code=1)

    out = _run(layout, "precompile_app_bytecode; echo still-running")

    assert "could not precompile" in out
    assert "still-running" in out

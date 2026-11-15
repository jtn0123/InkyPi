"""zram-tools must not fight the OS's own zram swap.

Pi OS Trixie's rpi-swap sets up /dev/zram0 through systemd-zram-generator.
``zram-tools`` used to be in ``debian-requirements.txt``, so it was installed
anyway, and its ``zramswap.service`` failed at every boot. These tests run the
real ``_common.sh`` functions with ``dpkg-query``, ``systemctl``, ``sudo`` and
``apt-get`` stubbed on ``PATH``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

INSTALL_DIR = Path(__file__).resolve().parents[2] / "install"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    *,
    swaps: str,
    installed: tuple[str, ...] = (),
    zramswap_unit: bool = False,
) -> tuple[str, list[str]]:
    """Run setup_zramswap_service; return its output and the logged commands."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    swaps_file = tmp_path / "swaps"
    swaps_file.write_text(swaps, encoding="utf-8")

    status_cases = "\n".join(
        f'  {pkg}) echo "install ok installed"; exit 0 ;;' for pkg in installed
    )
    _stub(
        bin_dir,
        "dpkg-query",
        f'case "${{@: -1}}" in\n{status_cases}\n  *) exit 1 ;;\nesac',
    )
    unit_listing = "echo 'zramswap.service disabled enabled'" if zramswap_unit else ""
    _stub(
        bin_dir,
        "systemctl",
        f'echo "systemctl $*" >> "{log}"\n'
        f'if [ "$1" = list-unit-files ]; then {unit_listing or ":"}; fi',
    )
    _stub(bin_dir, "sudo", f'echo "sudo $*" >> "{log}"\n"$@"')
    _stub(bin_dir, "apt-get", f'echo "apt-get $*" >> "{log}"')
    _stub(bin_dir, "tee", "cat > /dev/null")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "INKYPI_PROC_SWAPS": str(swaps_file),
    }
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{INSTALL_DIR / "_common.sh"}"; setup_zramswap_service',
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=30,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result.stdout, calls


_NO_SWAP = "Filename\tType\tSize\tUsed\tPriority\n"
_ZRAM_ACTIVE = _NO_SWAP + "/dev/zram0\tpartition\t414000\t0\t100\n"


@pytest.mark.parametrize(
    ("swaps", "installed"),
    [
        (_ZRAM_ACTIVE, ()),
        (_NO_SWAP, ("rpi-swap",)),
        (_NO_SWAP, ("systemd-zram-generator",)),
    ],
    ids=["zram-active", "rpi-swap-installed", "zram-generator-installed"],
)
def test_skips_zram_tools_when_the_os_provides_zram(
    tmp_path: Path, swaps: str, installed: tuple[str, ...]
) -> None:
    out, calls = _run(tmp_path, swaps=swaps, installed=installed)

    assert "skipping zram-tools install" in out
    assert not [c for c in calls if c.startswith("apt-get")]
    assert not [c for c in calls if "enable" in c]


def test_disables_a_leftover_zramswap_without_stopping_it(tmp_path: Path) -> None:
    out, calls = _run(
        tmp_path, swaps=_ZRAM_ACTIVE, installed=("rpi-swap",), zramswap_unit=True
    )

    assert "Disabled zram-tools' zramswap.service" in out
    assert "systemctl disable zramswap.service" in calls
    assert "systemctl reset-failed zramswap.service" in calls
    # Stopping it could swap off the live swap mid-update.
    assert not [c for c in calls if "--now" in c or c.startswith("systemctl stop")]


def test_installs_zram_tools_when_the_os_has_no_zram(tmp_path: Path) -> None:
    _out, calls = _run(tmp_path, swaps=_NO_SWAP)

    assert "apt-get install -y zram-tools" in calls
    assert "systemctl enable --now zramswap" in calls


def test_zram_tools_is_not_in_the_unconditional_package_list() -> None:
    packages = (INSTALL_DIR / "debian-requirements.txt").read_text(encoding="utf-8")

    assert "zram-tools" not in packages.split()

"""earlyoom is tuned to kill Chromium first and spare sshd, systemd and journald.

G7: Raspberry Pi OS boots with cgroup_disable=memory, so the service's
MemoryHigh/MemoryMax caps do nothing and earlyoom is the memory guard. On its
Debian defaults it ranked by oom_score alone and, on the owner's Pi, kept
killing 1-5 MiB desktop services. These tests run the real ``_common.sh``
functions with ``sudo``, ``systemctl`` and ``apt-get`` stubbed on ``PATH``
and the defaults file redirected with ``INKYPI_EARLYOOM_DEFAULTS``.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

INSTALL_DIR = Path(__file__).resolve().parents[2] / "install"

# /etc/default/earlyoom as Debian (and Raspberry Pi OS Trixie) ships it.
DEBIAN_DEFAULTS = """\
# Default settings for earlyoom. This file is sourced by /bin/sh from
# /etc/init.d/earlyoom or by systemd from earlyoom.service.

# Options to pass to earlyoom
EARLYOOM_ARGS="-r 3600"

# Examples:

# Print memory report every minute instead of every hour
# EARLYOOM_ARGS="-r 60"

# Avoid killing processes whose name matches this regexp
# EARLYOOM_ARGS="--avoid '(^|/)(init|X|sshd|firefox)$'"

# See more at `earlyoom -h'
"""


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


class _Env:
    def __init__(self, tmp_path: Path) -> None:
        self.defaults = tmp_path / "earlyoom"
        self.log = tmp_path / "calls.log"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _stub(bin_dir, "sudo", f'echo "sudo $*" >> "{self.log}"\n"$@"')
        _stub(bin_dir, "systemctl", f'echo "systemctl $*" >> "{self.log}"')
        _stub(bin_dir, "apt-get", f'echo "apt-get $*" >> "{self.log}"')
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "INKYPI_EARLYOOM_DEFAULTS": str(self.defaults),
        }

    def run(self, function: str) -> str:
        self.log.unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", "-c", f'source "{INSTALL_DIR / "_common.sh"}"; {function}'],
            capture_output=True,
            text=True,
            env=self.env,
            check=True,
            timeout=30,
        )
        return result.stdout

    def calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def restarts(self) -> list[str]:
        return [c for c in self.calls() if c == "systemctl restart earlyoom"]


@pytest.fixture
def setup(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


def _args_line(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("EARLYOOM_ARGS=")]


def _earlyoom_argv(defaults: Path) -> list[str]:
    """The argv earlyoom gets, by sourcing the file as the init script does.

    systemd's split of $EARLYOOM_ARGS matches it here: the value holds no
    quotes, backslashes or globbing characters.
    """
    out = subprocess.run(
        ["sh", "-c", f'. "{defaults}"; printf "%s\\n" $EARLYOOM_ARGS'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.splitlines()


def test_writes_the_args_and_restarts_earlyoom(setup: _Env) -> None:
    setup.defaults.write_text(DEBIAN_DEFAULTS)

    out = setup.run("configure_earlyoom")

    body = setup.defaults.read_text()
    assert len(_args_line(body)) == 1
    argv = _earlyoom_argv(setup.defaults)
    # Debian's report interval is kept.
    assert argv[:2] == ["-r", "3600"]
    prefer = re.compile(argv[argv.index("--prefer") + 1])
    avoid = re.compile(argv[argv.index("--avoid") + 1])
    # earlyoom matches /proc/PID/comm, cut to 15 bytes.
    for comm in ("chromium-headle", "chromium", "headless_shell", "chrome"):
        assert prefer.search(comm), comm
    for comm in ("python", "earlyoom", "sshd", "systemd", "wireplumber"):
        assert not prefer.search(comm), comm
    for comm in ("sshd", "sshd-session", "systemd", "systemd-journal"):
        assert avoid.search(comm), comm
    for comm in ("python", "chromium-headle", "systemd-logind"):
        assert not avoid.search(comm), comm
    assert setup.restarts() == ["systemctl restart earlyoom"]
    assert "Configured earlyoom" in out


def test_keeps_debians_comments_and_examples(setup: _Env) -> None:
    setup.defaults.write_text(DEBIAN_DEFAULTS)

    setup.run("configure_earlyoom")

    body = setup.defaults.read_text()
    for line in DEBIAN_DEFAULTS.splitlines():
        if not line.startswith("EARLYOOM_ARGS="):
            assert line in body.splitlines(), line
    # The managed line sits where Debian's was, under a marker.
    lines = body.splitlines()
    args_at = lines.index(_args_line(body)[0])
    assert lines[args_at - 1].startswith("# Set by InkyPi")


def test_a_second_run_changes_nothing_and_does_not_restart(setup: _Env) -> None:
    setup.defaults.write_text(DEBIAN_DEFAULTS)
    setup.run("configure_earlyoom")
    configured = setup.defaults.read_bytes()
    mtime = setup.defaults.stat().st_mtime_ns

    out = setup.run("configure_earlyoom")

    assert setup.defaults.read_bytes() == configured
    assert setup.defaults.stat().st_mtime_ns == mtime
    assert setup.restarts() == []
    assert not [c for c in setup.calls() if "tee" in c]
    assert "already" in out


def test_replaces_other_args_and_duplicate_lines(setup: _Env) -> None:
    """A hand edit or an older InkyPi line is replaced, once, in place."""
    setup.defaults.write_text(
        "# Set by InkyPi (install/_common.sh: configure_earlyoom).\n"
        'EARLYOOM_ARGS="-r 60"\n'
        "# keep me\n"
        'EARLYOOM_ARGS="-m 5"\n'
    )

    setup.run("configure_earlyoom")

    body = setup.defaults.read_text()
    assert len(_args_line(body)) == 1
    assert body.count("# Set by InkyPi") == 1
    assert "# keep me" in body
    assert "--prefer" in _args_line(body)[0]
    assert setup.restarts() == ["systemctl restart earlyoom"]


def test_creates_the_file_when_missing(setup: _Env) -> None:
    setup.run("configure_earlyoom")

    assert len(_args_line(setup.defaults.read_text())) == 1
    assert setup.restarts() == ["systemctl restart earlyoom"]


def test_setup_installs_enables_then_configures(setup: _Env) -> None:
    """install.sh and update.sh both call setup_earlyoom_service."""
    setup.defaults.write_text(DEBIAN_DEFAULTS)

    setup.run("setup_earlyoom_service")
    first = setup.calls()
    setup.run("setup_earlyoom_service")
    second = setup.calls()

    assert first.index("apt-get install -y earlyoom") < first.index(
        "systemctl enable --now earlyoom"
    )
    assert first.index("systemctl enable --now earlyoom") < first.index(
        "systemctl restart earlyoom"
    )
    assert "systemctl restart earlyoom" not in second


def test_install_and_update_both_set_up_earlyoom() -> None:
    for script in ("install.sh", "update.sh"):
        text = (INSTALL_DIR / script).read_text(encoding="utf-8")
        assert re.search(r"^setup_earlyoom_service$", text, re.M), script


def test_args_have_nothing_systemd_or_sh_would_reinterpret() -> None:
    """systemd splits $EARLYOOM_ARGS at whitespace and honours quotes; the
    init script expands it unquoted. Plain words survive both unchanged."""
    text = (INSTALL_DIR / "_common.sh").read_text(encoding="utf-8")
    match = re.search(r"^INKYPI_EARLYOOM_ARGS='([^']*)'$", text, re.M)
    assert match
    value = match.group(1)
    assert not set(value) & set("\"'\\*?[]`")
    assert shlex.split(value) == value.split()

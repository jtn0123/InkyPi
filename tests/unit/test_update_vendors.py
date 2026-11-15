"""install/update_vendors.sh only installs files that match their pinned hash.

Each case runs the real script from a scratch copy of the repo layout, with a
fake ``curl`` on PATH that writes a chosen body, so nothing touches the network.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "install" / "update_vendors.sh"
_SHA_RE = re.compile(r"\|([0-9a-f]{64})\"")

_FAKE_CURL = """#!/usr/bin/env bash
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; shift; fi
  shift
done
printf '%s' "$FAKE_CURL_BODY" > "$out"
"""


def _layout(tmp_path: Path, pin_body: str | None = None) -> Path:
    """Copy the script into tmp_path/install, optionally re-pinning every hash."""
    install = tmp_path / "install"
    install.mkdir()
    script = install / "update_vendors.sh"
    text = _SCRIPT.read_text()
    if pin_body is not None:
        digest = hashlib.sha256(pin_body.encode()).hexdigest()
        text = _SHA_RE.sub(f'|{digest}"', text)
    script.write_text(text)
    (tmp_path / "src" / "static" / "scripts").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(_FAKE_CURL)
    curl.chmod(0o755)
    return script


def _run(tmp_path: Path, script: Path, body: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env["FAKE_CURL_BODY"] = body
    return subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path / "install",
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _scripts_dir(tmp_path: Path) -> Path:
    return tmp_path / "src" / "static" / "scripts"


def test_every_vendor_file_has_a_pinned_sha256() -> None:
    entries = re.findall(
        r'^\s*"([^"|]+)\|https://[^"|]+\|[^"|]+\|([^"|]*)"', _SCRIPT.read_text(), re.M
    )
    assert len(entries) == 2
    for name, digest in entries:
        assert re.fullmatch(r"[0-9a-f]{64}", digest), f"{name} has no sha256"


def test_a_tampered_download_is_rejected_and_the_old_file_kept(tmp_path: Path) -> None:
    script = _layout(tmp_path)
    existing = _scripts_dir(tmp_path) / "chart.js"
    existing.write_text("previous good copy")

    result = _run(tmp_path, script, "alert('not chart.js')")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Chart JS failed its hash check" in result.stderr
    assert existing.read_text() == "previous good copy"
    assert not (_scripts_dir(tmp_path) / "calendar.min.js").exists()
    assert sorted(p.name for p in _scripts_dir(tmp_path).iterdir()) == ["chart.js"]


def test_a_matching_download_is_installed(tmp_path: Path) -> None:
    body = "/* vendor build */"
    script = _layout(tmp_path, pin_body=body)

    result = _run(tmp_path, script, body)

    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("chart.js", "calendar.min.js"):
        installed = _scripts_dir(tmp_path) / name
        assert installed.read_text() == body
        assert installed.stat().st_mode & 0o777 == 0o644
    assert sorted(p.name for p in _scripts_dir(tmp_path).iterdir()) == [
        "calendar.min.js",
        "chart.js",
    ]


def test_an_entry_without_a_hash_is_refused(tmp_path: Path) -> None:
    script = _layout(tmp_path)
    script.write_text(_SHA_RE.sub('|"', script.read_text(), count=1))

    result = _run(tmp_path, script, "anything")

    assert result.returncode == 1
    assert "has no pinned sha256" in result.stderr
    assert list(_scripts_dir(tmp_path).iterdir()) == []

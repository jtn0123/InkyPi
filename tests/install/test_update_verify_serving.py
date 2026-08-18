"""Functional cover for update.sh's post-update serving verification.

``systemctl is-active`` proves the unit started, not that the new build serves.
These tests run the real bash helpers against a real HTTP server so the three
outcomes — confirmed / unconfirmed / dark — are exercised end to end rather
than asserted against the script's source text.
"""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_SH = REPO_ROOT / "install" / "update.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("curl") is None,
    reason="requires bash and curl",
)


def _make_server(*, ready: bool, version: str | None) -> Any:
    """Serve just the two endpoints the verifier polls."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
            if self.path == "/readyz":
                if ready:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ready")
                else:
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b"not-ready")
                return
            if self.path == "/api/version/info":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"version": version or ""}).encode())
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args) -> None:  # silence per-request stderr noise
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _run_verify(
    tmp_path: Path, *, port: int, expected_version: str, timeout: str = "6"
) -> Any:
    """Source update.sh for its helpers, then call verify_app_serving."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    # SCRIPT_DIR/../VERSION is what the verifier compares against, so stage a
    # fake install tree rather than mutating the repo's VERSION.
    fake_install = tmp_path / "install"
    fake_install.mkdir(exist_ok=True)
    shutil.copy(UPDATE_SH, fake_install / "update.sh")
    shutil.copy(REPO_ROOT / "install" / "_common.sh", fake_install / "_common.sh")
    (tmp_path / "VERSION").write_text(expected_version + "\n")

    script = f"""
    set -uo pipefail
    export INKYPI_UPDATE_SOURCE_ONLY=1
    export INKYPI_LOCKFILE_DIR={state_dir!s}
    export INKYPI_PORT={port}
    export INKYPI_SERVICE_START_TIMEOUT={timeout}
    source {fake_install / "update.sh"!s}
    verify_app_serving
    echo "RC=$?"
    """
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=120
    )
    outcome_file = state_dir / ".last-update-outcome"
    outcome = json.loads(outcome_file.read_text()) if outcome_file.exists() else None
    return proc, outcome


def test_confirmed_when_serving_the_expected_version(tmp_path: Path) -> None:
    server = _make_server(ready=True, version="9.9.9")
    try:
        proc, outcome = _run_verify(
            tmp_path, port=server.server_address[1], expected_version="9.9.9"
        )
    finally:
        server.shutdown()

    assert "RC=0" in proc.stdout, proc.stdout + proc.stderr
    assert outcome is not None
    assert outcome["verdict"] == "confirmed"
    assert outcome["observed_version"] == "9.9.9"
    assert outcome["expected_version"] == "9.9.9"


def test_unconfirmed_when_a_stale_version_answers(tmp_path: Path) -> None:
    """The exact gap: the unit is up, but it is not the build we installed."""
    server = _make_server(ready=True, version="1.0.0")
    try:
        proc, outcome = _run_verify(
            tmp_path, port=server.server_address[1], expected_version="9.9.9"
        )
    finally:
        server.shutdown()

    assert "RC=1" in proc.stdout, proc.stdout + proc.stderr
    assert outcome is not None
    assert outcome["verdict"] == "unconfirmed"
    assert outcome["observed_version"] == "1.0.0"
    assert outcome["expected_version"] == "9.9.9"


def test_unconfirmed_when_never_becomes_ready(tmp_path: Path) -> None:
    server = _make_server(ready=False, version="9.9.9")
    try:
        proc, outcome = _run_verify(
            tmp_path, port=server.server_address[1], expected_version="9.9.9"
        )
    finally:
        server.shutdown()

    assert "RC=1" in proc.stdout, proc.stdout + proc.stderr
    assert outcome is not None
    # Nothing ever answered /readyz, so from the verifier's view it is dark.
    assert outcome["verdict"] == "dark"


def test_dark_when_nothing_is_listening(tmp_path: Path) -> None:
    # Bind and immediately release a port so we know nothing is on it.
    server = _make_server(ready=True, version="9.9.9")
    port = server.server_address[1]
    server.shutdown()
    server.server_close()

    proc, outcome = _run_verify(tmp_path, port=port, expected_version="9.9.9")

    assert "RC=1" in proc.stdout, proc.stdout + proc.stderr
    assert outcome is not None
    assert outcome["verdict"] == "dark"
    assert outcome["observed_version"] == ""


def test_ready_is_enough_when_no_version_is_available(tmp_path: Path) -> None:
    """An empty VERSION leaves nothing to compare; readiness is the best claim."""
    server = _make_server(ready=True, version="")
    try:
        proc, outcome = _run_verify(
            tmp_path, port=server.server_address[1], expected_version=""
        )
    finally:
        server.shutdown()

    assert "RC=0" in proc.stdout, proc.stdout + proc.stderr
    assert outcome is not None
    assert outcome["verdict"] == "confirmed"


def test_update_script_runs_verification_after_starting_the_service(
    tmp_path: Path,
) -> None:
    """Ordering matters: verification is meaningless before the unit is active."""
    content = UPDATE_SH.read_text()
    assert content.index("update_app_service\n") < content.index("verify_app_serving\n")

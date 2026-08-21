from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from flask.testing import FlaskClient


def test_missing_state_directory_degrades_gracefully(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import blueprints.diagnostics as diag

    state_dir = tmp_path / "var-lib-inkypi"
    state_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(state_dir)

    monkeypatch.setattr(diag, "_PREV_VERSION_PATH", state_dir / "prev_version")
    monkeypatch.setattr(
        diag,
        "_LAST_UPDATE_FAILURE_PATH",
        state_dir / ".last-update-failure",
    )

    diagnostics = client.get("/api/diagnostics")
    assert diagnostics.status_code == 200
    payload = diagnostics.get_json()
    assert payload["last_update_failure"] is None

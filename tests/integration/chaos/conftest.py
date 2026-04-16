from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def chaos_diag_paths(tmp_path, monkeypatch):
    """Isolate diagnostics filesystem paths per test and allow dev access."""
    import blueprints.diagnostics as diag

    prev_path = tmp_path / "prev_version"
    failure_path = tmp_path / ".last-update-failure"

    monkeypatch.setenv("INKYPI_ENV", "dev")
    monkeypatch.setattr(diag, "_PREV_VERSION_PATH", prev_path)
    monkeypatch.setattr(diag, "_LAST_UPDATE_FAILURE_PATH", failure_path)

    return {
        "prev": prev_path,
        "failure": failure_path,
    }

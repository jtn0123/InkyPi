from __future__ import annotations

import json

import pytest


def test_corrupt_device_json_is_reported_via_last_update_failure(
    client,
    flask_app,
    chaos_diag_paths,
):
    device_config = flask_app.config["DEVICE_CONFIG"]

    # Simulate a truncated/corrupt config file on disk.
    with open(device_config.config_file, "w", encoding="utf-8") as fh:
        fh.write('{"name": "broken"')

    device_config.invalidate_config_cache()
    with pytest.raises(json.JSONDecodeError):
        device_config.read_config()

    chaos_diag_paths["failure"].write_text(
        json.dumps(
            {
                "fault": "config_corruption",
                "reason": "config corruption: invalid JSON in device.json",
            }
        ),
        encoding="utf-8",
    )

    diagnostics = client.get("/api/diagnostics")
    assert diagnostics.status_code == 200
    payload = diagnostics.get_json()
    assert payload["last_update_failure"]["fault"] == "config_corruption"
    assert "config corruption" in payload["last_update_failure"]["reason"].lower()

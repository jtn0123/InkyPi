import json
import logging
import os


def test_update_config_writes_atomically(device_config_dev, tmp_path):
    """Bug 10: update_config should write inside the lock to prevent races."""
    device_config_dev.update_config({"name": "Atomic"})
    assert device_config_dev.get_config("name") == "Atomic"
    # Read back from disk to verify write happened
    with open(device_config_dev.config_file) as f:
        on_disk = json.load(f)
    assert on_disk["name"] == "Atomic"


def test_update_value_writes_atomically(device_config_dev, tmp_path):
    """Bug 10: update_value with write=True should write inside the lock."""
    device_config_dev.update_value("name", "AtomicVal", write=True)
    assert device_config_dev.get_config("name") == "AtomicVal"
    with open(device_config_dev.config_file) as f:
        on_disk = json.load(f)
    assert on_disk["name"] == "AtomicVal"


def test_config_logging_is_sanitized(monkeypatch, tmp_path, caplog):
    import config as config_mod

    # Build a minimal config that includes sensitive-looking fields
    cfg_content = {
        "name": "Test",
        "resolution": [800, 480],
        "playlist_config": {
            "playlists": [
                {
                    "name": "Default",
                    "start_time": "00:00",
                    "end_time": "24:00",
                    "plugins": [
                        {
                            "plugin_id": "ai_image",
                            "name": "Instance",
                            "plugin_settings": {"OPEN_AI_SECRET": "super-secret-value"},
                            "refresh": {"interval": 60},
                        }
                    ],
                }
            ],
            "active_playlist": "",
        },
        # Fields that look sensitive
        "api_token": "token-123",
        "somePassword": "pwd",
        "weather_api_key": "key-xyz",
    }

    cfg_path = tmp_path / "device.json"
    os.makedirs(tmp_path, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg_content))

    monkeypatch.setattr(config_mod.Config, "config_file", str(cfg_path))

    # Capture debug logs by lowering the root logger level for the duration of this test
    caplog.set_level(logging.DEBUG)
    _cfg = config_mod.Config()

    # Ensure debug log contains sanitized markers and not raw secrets
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "Loaded config (sanitized):" in full_log
    # Sensitive fields should be masked
    assert "token-123" not in full_log
    assert "pwd" not in full_log
    assert "key-xyz" not in full_log
    # Plugin settings should not leak raw values
    assert "super-secret-value" not in full_log
    # But summary data should exist
    assert "num_plugins" in full_log



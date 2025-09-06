import json
import logging
import os


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
            "active_playlist": None,
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



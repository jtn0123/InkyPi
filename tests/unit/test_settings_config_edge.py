# pyright: reportMissingImports=false
"""Edge-case tests for settings config routes (_config.py).

Supplements test_settings_blueprint.py with untested error branches.
"""

import io
from unittest.mock import MagicMock


class TestIsolation:
    def test_stored_non_list_normalized(self, client, device_config_dev):
        """isolated_plugins stored as a string → GET normalizes to list."""
        device_config_dev.update_value("isolated_plugins", "not-a-list", write=True)

        resp = client.get("/settings/isolation")
        data = resp.get_json()
        assert data["success"] is True
        assert isinstance(data["isolated_plugins"], list)
        assert data["isolated_plugins"] == []


class TestSafeReset:
    def test_preserves_display_type(self, client, device_config_dev):
        """display_type survives safe reset."""
        device_config_dev.update_value("display_type", "mock", write=True)

        resp = client.post("/settings/safe_reset")
        assert resp.status_code == 200

        config = device_config_dev.get_config()
        assert config["display_type"] == "mock"

    def test_preserves_resolution(self, client, device_config_dev):
        """resolution survives safe reset."""
        device_config_dev.update_value("resolution", [1200, 825], write=True)

        resp = client.post("/settings/safe_reset")
        assert resp.status_code == 200

        config = device_config_dev.get_config()
        assert config["resolution"] == [1200, 825]

    def test_sets_interval_3600(self, client, device_config_dev):
        """Safe reset sets plugin_cycle_interval_seconds to 3600."""
        device_config_dev.update_value("plugin_cycle_interval_seconds", 60, write=True)

        resp = client.post("/settings/safe_reset")
        assert resp.status_code == 200

        config = device_config_dev.get_config()
        assert config["plugin_cycle_interval_seconds"] == 3600


class TestExportEdge:
    def test_get_config_failure_500(self, client, monkeypatch):
        """get_config() raising returns 500."""
        import config as config_mod

        monkeypatch.setattr(
            config_mod.Config,
            "get_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        resp = client.get("/settings/export")
        assert resp.status_code == 500

    def test_load_env_key_raises_partial(self, client, device_config_dev, monkeypatch):
        """One key raising during export → others still exported."""

        call_count = 0
        original = device_config_dev.load_env_key

        def _flaky_load(key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("read error")
            return original(key)

        monkeypatch.setattr(device_config_dev, "load_env_key", _flaky_load)

        resp = client.get("/settings/export?include_keys=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # Should have attempted all keys, first one failed gracefully
        assert "data" in data


class TestImportEdge:
    def test_env_key_set_failure_continues(
        self, client, device_config_dev, monkeypatch
    ):
        """set_env_key raises for first key → subsequent keys still attempted."""
        call_log = []
        original_set = device_config_dev.set_env_key

        def _failing_set(key, value):
            call_log.append(key)
            if len(call_log) == 1:
                raise OSError("write error")
            return original_set(key, value)

        monkeypatch.setattr(device_config_dev, "set_env_key", _failing_set)

        payload = {
            "config": {"name": "Test"},
            "env_keys": {
                "OPEN_AI_SECRET": "key1",
                "NASA_SECRET": "key2",
            },
        }
        resp = client.post(
            "/settings/import",
            json=payload,
        )
        assert resp.status_code == 200
        # Both keys were attempted
        assert len(call_log) == 2

    def test_malformed_file_upload(self, client):
        """Upload non-JSON file returns error."""
        data = {"file": (io.BytesIO(b"not json at all"), "settings.json")}
        resp = client.post(
            "/settings/import",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 500  # json.loads will raise

    def test_only_env_keys_no_config(self, client, device_config_dev, monkeypatch):
        """Payload with env_keys but no config key still processes env keys."""
        set_calls = []
        original_set = device_config_dev.set_env_key

        def _tracking_set(key, value):
            set_calls.append(key)
            return original_set(key, value)

        monkeypatch.setattr(device_config_dev, "set_env_key", _tracking_set)

        payload = {"env_keys": {"NASA_SECRET": "my-key"}}
        resp = client.post("/settings/import", json=payload)
        # No "config" key means cfg is None → isinstance(None, dict) is False → skipped
        # env_keys should still be processed
        assert resp.status_code == 200
        assert "NASA_SECRET" in set_calls


class TestSaveSettingsEdge:
    def _valid_form(self, **overrides):
        form = {
            "unit": "minute",
            "interval": "5",
            "timezoneName": "UTC",
            "timeFormat": "24h",
            "deviceName": "Test",
            "orientation": "horizontal",
            "saturation": "1.0",
            "brightness": "1.0",
            "sharpness": "1.0",
            "contrast": "1.0",
        }
        form.update(overrides)
        return form

    def test_interval_zero_rejected(self, client):
        """interval=0 returns 422."""
        resp = client.post("/save_settings", data=self._valid_form(interval="0"))
        assert resp.status_code == 422

    def test_interval_over_24h_rejected(self, client):
        """>86400 seconds returns 422."""
        # 1500 minutes = 90000 seconds > 86400
        resp = client.post("/save_settings", data=self._valid_form(interval="1500"))
        assert resp.status_code == 422

    def test_non_numeric_saturation_500(self, client, device_config_dev):
        """Non-float saturation causes ValueError → 500."""
        resp = client.post(
            "/save_settings",
            data=self._valid_form(saturation="not-a-number"),
        )
        assert resp.status_code == 500

    def test_runtime_error_500(self, client, device_config_dev, monkeypatch):
        """update_config raising RuntimeError → 500."""
        monkeypatch.setattr(
            device_config_dev,
            "update_config",
            MagicMock(side_effect=RuntimeError("config write failed")),
        )

        resp = client.post("/save_settings", data=self._valid_form())
        assert resp.status_code == 500

    def test_generic_exception_500(self, client, device_config_dev, monkeypatch):
        """Generic Exception from update_config → 500."""
        monkeypatch.setattr(
            device_config_dev,
            "update_config",
            MagicMock(side_effect=Exception("unexpected")),
        )

        resp = client.post("/save_settings", data=self._valid_form())
        assert resp.status_code == 500

    def test_unchanged_interval_no_signal(self, client, device_config_dev, monkeypatch):
        """Same interval as current → signal_config_change NOT called."""
        # Set current interval to match what we'll POST
        device_config_dev.update_value("plugin_cycle_interval_seconds", 300, write=True)

        rt = client.application.config["REFRESH_TASK"]
        signal_mock = MagicMock()
        monkeypatch.setattr(rt, "signal_config_change", signal_mock)

        resp = client.post("/save_settings", data=self._valid_form())
        assert resp.status_code == 200
        signal_mock.assert_not_called()


class TestApiKeysMask:
    def test_mask_short_key(self, client, device_config_dev, monkeypatch):
        """Key < 4 chars shows 'set (N chars)' pattern."""
        monkeypatch.setattr(
            device_config_dev,
            "load_env_key",
            lambda k: "abc" if k == "NASA_SECRET" else None,
        )

        resp = client.get("/settings/api-keys")
        assert resp.status_code == 200
        assert b"set (3 chars)" in resp.data

    def test_mask_empty_string(self, client, device_config_dev, monkeypatch):
        """Empty string key returns None mask (not displayed as 'set')."""
        monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "")

        resp = client.get("/settings/api-keys")
        assert resp.status_code == 200
        # Empty string → mask returns None → should not display "set" or "chars"
        assert b"set (" not in resp.data


class TestDeleteApiKeyEdge:
    def test_unset_exception_500(self, client, device_config_dev, monkeypatch):
        """unset_env_key raising returns 500."""
        monkeypatch.setattr(
            device_config_dev,
            "unset_env_key",
            MagicMock(side_effect=OSError("permission denied")),
        )

        resp = client.post(
            "/settings/delete_api_key",
            data={"key": "NASA_SECRET"},
        )
        assert resp.status_code == 500

# pyright: reportMissingImports=false
"""Tests for screenshot plugin URL scheme validation at save time (JTN-456).

The Screenshot plugin must reject non-http(s) URLs when settings are saved,
not just when generate_image is called.  This prevents unsafe values (e.g.
file:// or javascript:) from being persisted to device.json.
"""

# ---------------------------------------------------------------------------
# /save_plugin_settings  (POST)
# ---------------------------------------------------------------------------


class TestSavePluginSettingsUrlValidation:
    """Verify that /save_plugin_settings enforces URL scheme for screenshot."""

    def test_javascript_url_rejected_on_save(self, client):
        """javascript: URLs must be rejected at save time with HTTP 400."""
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "screenshot", "url": "javascript:alert(1)"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid URL" in data.get("error", "")

    def test_file_url_rejected_on_save(self, client):
        """file:// URLs must be rejected at save time with HTTP 400."""
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "screenshot", "url": "file:///etc/passwd"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid URL" in data.get("error", "")

    def test_data_url_rejected_on_save(self, client):
        """data: URLs must be rejected at save time with HTTP 400."""
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "screenshot", "url": "data:text/html,<h1>hi</h1>"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid URL" in data.get("error", "")

    def test_ftp_url_rejected_on_save(self, client):
        """ftp:// URLs must be rejected at save time with HTTP 400."""
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "screenshot", "url": "ftp://files.example.com/"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid URL" in data.get("error", "")

    def test_http_url_accepted_on_save(self, client, monkeypatch):
        """http:// URLs with a public hostname must be accepted (HTTP 200)."""
        import socket

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **kw: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
            ],
        )
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "screenshot", "url": "http://example.com"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True

    def test_https_url_accepted_on_save(self, client, monkeypatch):
        """https:// URLs with a public hostname must be accepted (HTTP 200)."""
        import socket

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **kw: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
            ],
        )
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "screenshot", "url": "https://example.com"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True


# ---------------------------------------------------------------------------
# /plugin/<plugin_id>/save  (POST alias)
# ---------------------------------------------------------------------------


class TestSaveAliasUrlValidation:
    """Verify the alias route /plugin/screenshot/save also enforces URL scheme."""

    def test_javascript_url_rejected_via_alias(self, client):
        """javascript: URL is rejected through the alias save route."""
        resp = client.post(
            "/plugin/screenshot/save",
            data={"url": "javascript:alert(1)"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid URL" in data.get("error", "")

    def test_file_url_rejected_via_alias(self, client):
        """file:// URL is rejected through the alias save route."""
        resp = client.post(
            "/plugin/screenshot/save",
            data={"url": "file:///etc/passwd"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid URL" in data.get("error", "")

    def test_https_url_accepted_via_alias(self, client, monkeypatch):
        """https:// URL is accepted through the alias save route."""
        import socket

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **kw: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
            ],
        )
        resp = client.post(
            "/plugin/screenshot/save",
            data={"url": "https://example.com"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True


# ---------------------------------------------------------------------------
# /update_plugin_instance/<name>  (PUT)
# ---------------------------------------------------------------------------


class TestUpdateInstanceUrlValidation:
    """Verify that updating an existing screenshot instance also validates URL."""

    def _create_instance(self, device_config_dev, name="screenshot_test_instance"):
        """Helper: create a screenshot plugin instance on the Default playlist."""
        pm = device_config_dev.get_playlist_manager()
        if not pm.get_playlist("Default"):
            pm.add_playlist("Default")
        playlist = pm.get_playlist("Default")
        playlist.add_plugin(
            {
                "plugin_id": "screenshot",
                "name": name,
                "plugin_settings": {"url": "https://example.com"},
                "refresh": {"interval": 3600},
            }
        )
        device_config_dev.write_config()
        return name

    def test_update_rejects_javascript_url(self, client, device_config_dev):
        """javascript: URL is rejected when updating an existing screenshot instance."""
        name = self._create_instance(device_config_dev)
        resp = client.put(
            f"/update_plugin_instance/{name}",
            data={"plugin_id": "screenshot", "url": "javascript:alert(1)"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid URL" in data.get("error", "")

    def test_update_rejects_file_url(self, client, device_config_dev):
        """file:// URL is rejected when updating an existing screenshot instance."""
        name = self._create_instance(device_config_dev, "screenshot_file_test")
        resp = client.put(
            f"/update_plugin_instance/{name}",
            data={"plugin_id": "screenshot", "url": "file:///etc/shadow"},
        )
        assert resp.status_code == 400

    def test_update_accepts_https_url(self, client, device_config_dev, monkeypatch):
        """https:// URL is accepted when updating an existing screenshot instance."""
        import socket

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **kw: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
            ],
        )
        name = self._create_instance(device_config_dev, "screenshot_https_test")
        resp = client.put(
            f"/update_plugin_instance/{name}",
            data={"plugin_id": "screenshot", "url": "https://example.com/page"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True

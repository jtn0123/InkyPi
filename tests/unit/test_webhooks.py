# pyright: reportMissingImports=false
"""Tests for the webhook notification helper (JTN-449).

Covers:
- send_failure_webhook posts JSON to each URL
- Timeout does not raise
- Connection error does not raise
- Empty URL list is a no-op
- Each POST result (success/failure) is logged
- Integration: _cb_on_failure triggers the webhook when webhook_urls is set
"""

import logging
from unittest.mock import MagicMock, patch

import requests

from model import PluginInstance
from refresh_task import RefreshTask
from utils.webhooks import send_failure_webhook

# ---------------------------------------------------------------------------
# Helpers shared with circuit-breaker tests
# ---------------------------------------------------------------------------


def _make_task(device_config_dev):
    dm = MagicMock()
    return RefreshTask(device_config_dev, dm)


def _make_plugin_instance(plugin_id="weather", name="my_weather"):
    return PluginInstance(
        plugin_id=plugin_id,
        name=name,
        settings={},
        refresh={"interval": 3600},
    )


def _add_plugin_to_pm(device_config_dev, plugin_instance):
    pm = device_config_dev.get_playlist_manager()
    playlist = pm.get_playlist("Default")
    if playlist is None:
        pm.add_default_playlist()
        playlist = pm.get_playlist("Default")
    playlist.plugins.append(plugin_instance)
    return pm


# ---------------------------------------------------------------------------
# Unit tests for send_failure_webhook
# ---------------------------------------------------------------------------


class TestSendFailureWebhook:
    def test_posts_json_to_each_url(self, requests_mock):
        urls = ["https://example.com/hook1", "https://example.com/hook2"]
        for url in urls:
            requests_mock.post(url, status_code=200)

        payload = {"event": "plugin_failure", "plugin_id": "weather"}
        send_failure_webhook(urls, payload)

        assert requests_mock.call_count == 2
        for i, url in enumerate(urls):
            history = requests_mock.request_history[i]
            assert history.url == url
            assert history.json() == payload

    def test_empty_url_list_is_noop(self, requests_mock):
        send_failure_webhook([], {"event": "plugin_failure"})
        assert requests_mock.call_count == 0

    def test_timeout_does_not_raise(self, requests_mock):
        requests_mock.post(
            "https://example.com/slow",
            exc=requests.exceptions.Timeout("timed out"),
        )
        # Must not raise
        send_failure_webhook(["https://example.com/slow"], {"event": "plugin_failure"})

    def test_connection_error_does_not_raise(self, requests_mock):
        requests_mock.post(
            "https://example.com/down",
            exc=requests.exceptions.ConnectionError("refused"),
        )
        # Must not raise
        send_failure_webhook(["https://example.com/down"], {"event": "plugin_failure"})

    def test_success_is_logged(self, requests_mock, caplog):
        requests_mock.post("https://example.com/hook", status_code=204)
        with caplog.at_level(logging.INFO, logger="utils.webhooks"):
            send_failure_webhook(
                ["https://example.com/hook"], {"event": "plugin_failure"}
            )
        assert any("sent" in r.message for r in caplog.records)

    def test_failure_is_logged(self, requests_mock, caplog):
        requests_mock.post(
            "https://example.com/hook",
            exc=requests.exceptions.ConnectionError("refused"),
        )
        with caplog.at_level(logging.WARNING, logger="utils.webhooks"):
            send_failure_webhook(
                ["https://example.com/hook"], {"event": "plugin_failure"}
            )
        assert any("failed" in r.message for r in caplog.records)

    def test_second_url_is_still_called_after_first_fails(self, requests_mock):
        requests_mock.post(
            "https://example.com/hook1",
            exc=requests.exceptions.ConnectionError("refused"),
        )
        requests_mock.post("https://example.com/hook2", status_code=200)

        send_failure_webhook(
            ["https://example.com/hook1", "https://example.com/hook2"],
            {"event": "plugin_failure"},
        )

        assert requests_mock.call_count == 2

    def test_uses_explicit_timeout(self, requests_mock):
        """Verify the timeout kwarg is passed through to requests.post."""
        requests_mock.post("https://example.com/hook", status_code=200)

        with patch("utils.webhooks.requests.post", wraps=requests.post) as mock_post:
            # requests_mock intercepts the actual HTTP call; we just check kwargs
            send_failure_webhook(
                ["https://example.com/hook"], {"event": "plugin_failure"}, timeout=0.5
            )
            _args, kwargs = mock_post.call_args
            assert kwargs.get("timeout") == 0.5


# ---------------------------------------------------------------------------
# Integration: _cb_on_failure calls send_failure_webhook
# ---------------------------------------------------------------------------


class TestCbOnFailureWebhookIntegration:
    def test_webhook_called_on_plugin_failure(self, device_config_dev, monkeypatch):
        """When webhook_urls is configured, _cb_on_failure should invoke the webhook."""
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        # Patch device_config.get_config to return a webhook URL for webhook_urls key
        original_get_config = device_config_dev.get_config

        def patched_get_config(key, default=None):
            if key == "webhook_urls":
                return ["https://example.com/hook"]
            return original_get_config(key, default)

        device_config_dev.get_config = patched_get_config

        with patch("refresh_task.task.send_failure_webhook") as mock_send:
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="API error",
            )

        mock_send.assert_called_once()
        _args, _kwargs = mock_send.call_args
        urls, payload = _args[0], _args[1]
        assert urls == ["https://example.com/hook"]
        assert payload["event"] == "plugin_failure"
        assert payload["plugin_id"] == "weather"
        assert payload["instance_name"] == "my_weather"
        assert "ts" in payload

    def test_webhook_not_called_when_no_urls_configured(
        self, device_config_dev, monkeypatch
    ):
        """When webhook_urls is empty, send_failure_webhook should not be called."""
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        with patch("refresh_task.task.send_failure_webhook") as mock_send:
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="API error",
            )

        mock_send.assert_not_called()

    def test_webhook_called_when_circuit_breaker_trips(
        self, device_config_dev, monkeypatch
    ):
        """Webhook fires even on the failure that triggers the circuit breaker."""
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "2")

        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        original_get_config = device_config_dev.get_config

        def patched_get_config(key, default=None):
            if key == "webhook_urls":
                return ["https://example.com/hook"]
            return original_get_config(key, default)

        device_config_dev.get_config = patched_get_config

        call_count = 0

        def counting_send(urls, payload, timeout=1.0):
            nonlocal call_count
            call_count += 1

        with patch("refresh_task.task.send_failure_webhook", side_effect=counting_send):
            # First failure — counter = 1, not yet paused
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="API error",
            )
            # Second failure — circuit breaker trips (paused = True) and webhook fires
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="API error again",
            )

        # Both failures should have triggered the webhook (paused check is inside
        # _cb_on_failure and short-circuits further calls once paused)
        assert call_count == 2

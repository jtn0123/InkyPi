"""Tests for RefreshContext dataclass and its integration with RefreshTask/worker."""

import pickle
from unittest.mock import MagicMock, patch

import pytest

from refresh_task.context import RefreshContext


class TestRefreshContext:
    """Unit tests for the RefreshContext dataclass."""

    def test_from_config_captures_all_fields(self):
        """RefreshContext.from_config should snapshot all relevant Config fields."""
        mock_config = MagicMock()
        mock_config.config_file = "/tmp/device.json"
        mock_config.current_image_file = "/tmp/current.png"
        mock_config.processed_image_file = "/tmp/processed.png"
        mock_config.plugin_image_dir = "/tmp/plugins"
        mock_config.history_image_dir = "/tmp/history"
        mock_config.get_resolution.return_value = (800, 480)
        mock_config.get_config.return_value = "America/New_York"

        ctx = RefreshContext.from_config(mock_config)

        assert ctx.config_file == "/tmp/device.json"
        assert ctx.current_image_file == "/tmp/current.png"
        assert ctx.processed_image_file == "/tmp/processed.png"
        assert ctx.plugin_image_dir == "/tmp/plugins"
        assert ctx.history_image_dir == "/tmp/history"
        assert ctx.resolution == (800, 480)
        assert ctx.timezone == "America/New_York"

    def test_from_config_defaults_timezone_to_utc(self):
        """When timezone config is missing or None, default to UTC."""
        mock_config = MagicMock()
        mock_config.config_file = "/tmp/device.json"
        mock_config.current_image_file = "/tmp/current.png"
        mock_config.processed_image_file = "/tmp/processed.png"
        mock_config.plugin_image_dir = "/tmp/plugins"
        mock_config.history_image_dir = "/tmp/history"
        mock_config.get_resolution.return_value = (600, 400)
        mock_config.get_config.return_value = None

        ctx = RefreshContext.from_config(mock_config)

        assert ctx.timezone == "UTC"

    def test_from_config_handles_get_config_exception(self):
        """When get_config raises, timezone should fall back to UTC."""
        mock_config = MagicMock()
        mock_config.config_file = "/tmp/device.json"
        mock_config.current_image_file = "/tmp/current.png"
        mock_config.processed_image_file = "/tmp/processed.png"
        mock_config.plugin_image_dir = "/tmp/plugins"
        mock_config.history_image_dir = "/tmp/history"
        mock_config.get_resolution.return_value = (800, 480)
        mock_config.get_config.side_effect = RuntimeError("config error")

        ctx = RefreshContext.from_config(mock_config)

        assert ctx.timezone == "UTC"

    def test_pickle_roundtrip(self):
        """RefreshContext must survive pickle serialisation (subprocess boundary)."""
        ctx = RefreshContext(
            config_file="/tmp/device.json",
            current_image_file="/tmp/current.png",
            processed_image_file="/tmp/processed.png",
            plugin_image_dir="/tmp/plugins",
            history_image_dir="/tmp/history",
            resolution=(800, 480),
            timezone="Europe/London",
        )

        pickled = pickle.dumps(ctx)
        restored = pickle.loads(pickled)

        assert restored == ctx
        assert restored.resolution == (800, 480)
        assert restored.timezone == "Europe/London"

    def test_frozen_immutability(self):
        """RefreshContext fields should not be mutable after creation."""
        ctx = RefreshContext(
            config_file="/tmp/device.json",
            current_image_file="/tmp/current.png",
            processed_image_file="/tmp/processed.png",
            plugin_image_dir="/tmp/plugins",
            history_image_dir="/tmp/history",
            resolution=(800, 480),
            timezone="UTC",
        )
        with pytest.raises(AttributeError):
            ctx.timezone = "US/Eastern"

    def test_restore_child_config(self):
        """restore_child_config should set Config class attrs and return an instance."""
        ctx = RefreshContext(
            config_file="/tmp/device.json",
            current_image_file="/tmp/current.png",
            processed_image_file="/tmp/processed.png",
            plugin_image_dir="/tmp/plugins",
            history_image_dir="/tmp/history",
            resolution=(800, 480),
            timezone="UTC",
        )

        mock_config_instance = MagicMock()
        with patch("config.Config") as MockConfig:
            MockConfig.return_value = mock_config_instance

            result = ctx.restore_child_config()

            assert MockConfig.config_file == "/tmp/device.json"
            assert MockConfig.current_image_file == "/tmp/current.png"
            assert MockConfig.processed_image_file == "/tmp/processed.png"
            assert MockConfig.plugin_image_dir == "/tmp/plugins"
            assert MockConfig.history_image_dir == "/tmp/history"
            assert result is mock_config_instance


class TestWorkerRefreshContextIntegration:
    """Tests that worker.py correctly handles RefreshContext."""

    def test_restore_child_config_with_refresh_context(self):
        """_restore_child_config should delegate to RefreshContext.restore_child_config."""
        from refresh_task.worker import _restore_child_config

        ctx = RefreshContext(
            config_file="/tmp/device.json",
            current_image_file="/tmp/current.png",
            processed_image_file="/tmp/processed.png",
            plugin_image_dir="/tmp/plugins",
            history_image_dir="/tmp/history",
            resolution=(800, 480),
            timezone="UTC",
        )

        mock_config_instance = MagicMock()
        # Config is imported lazily inside restore_child_config, so patch
        # at the canonical module level.
        with patch("config.Config") as MockConfig:
            MockConfig.return_value = mock_config_instance
            result = _restore_child_config(ctx)
            assert result is mock_config_instance
            # Verify it set the paths from RefreshContext
            assert MockConfig.config_file == "/tmp/device.json"
            assert MockConfig.plugin_image_dir == "/tmp/plugins"

    def test_restore_child_config_legacy_fallback(self):
        """_restore_child_config should still work with a legacy Config-like object."""
        from refresh_task.worker import _restore_child_config

        legacy_config = MagicMock()
        legacy_config.config_file = "/tmp/device.json"
        legacy_config.current_image_file = "/tmp/current.png"
        legacy_config.processed_image_file = "/tmp/processed.png"
        legacy_config.plugin_image_dir = "/tmp/plugins"
        legacy_config.history_image_dir = "/tmp/history"

        mock_config_instance = MagicMock()
        # Config is imported lazily in the legacy branch, patch at canonical module.
        with patch("config.Config") as MockConfig:
            MockConfig.return_value = mock_config_instance

            result = _restore_child_config(legacy_config)

            assert MockConfig.config_file == "/tmp/device.json"
            assert result is mock_config_instance


class TestRefreshTaskContextIntegration:
    """Tests that RefreshTask builds and uses RefreshContext."""

    def test_refresh_task_creates_context(self):
        """RefreshTask.__init__ should build a RefreshContext from device_config."""
        from refresh_task.task import RefreshTask

        mock_config = MagicMock()
        mock_config.config_file = "/tmp/device.json"
        mock_config.current_image_file = "/tmp/current.png"
        mock_config.processed_image_file = "/tmp/processed.png"
        mock_config.plugin_image_dir = "/tmp/plugins"
        mock_config.history_image_dir = "/tmp/history"
        mock_config.get_resolution.return_value = (800, 480)
        mock_config.get_config.return_value = "UTC"

        mock_display = MagicMock()

        task = RefreshTask(mock_config, mock_display)

        assert isinstance(task.refresh_context, RefreshContext)
        assert task.refresh_context.config_file == "/tmp/device.json"
        assert task.refresh_context.resolution == (800, 480)

    def test_signal_config_change_rebuilds_context(self):
        """signal_config_change should rebuild the RefreshContext snapshot."""
        from refresh_task.task import RefreshTask

        mock_config = MagicMock()
        mock_config.config_file = "/tmp/device.json"
        mock_config.current_image_file = "/tmp/current.png"
        mock_config.processed_image_file = "/tmp/processed.png"
        mock_config.plugin_image_dir = "/tmp/plugins"
        mock_config.history_image_dir = "/tmp/history"
        mock_config.get_resolution.return_value = (800, 480)
        mock_config.get_config.return_value = "UTC"

        mock_display = MagicMock()
        task = RefreshTask(mock_config, mock_display)

        original_ctx = task.refresh_context

        # Simulate config change
        mock_config.get_resolution.return_value = (1024, 768)
        task.signal_config_change()

        assert task.refresh_context is not original_ctx
        assert task.refresh_context.resolution == (1024, 768)

# pyright: reportMissingImports=false
from PIL import Image


def test_interval_refresh_logic_without_thread(device_config_dev, monkeypatch):
    # Create a playlist with one plugin instance
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("P1", "12:00", "13:00")
    pm.add_plugin_to_playlist("P1", {
        "plugin_id": "ai_text",
        "name": "inst",
        "plugin_settings": {"title": "T", "textModel": "gpt-4o", "textPrompt": "Hi"},
        "refresh": {"interval": 1}
    })

    # Set latest refresh to None so it's due
    device_config_dev.refresh_info.refresh_time = None

    # Mock plugin image generation
    import plugins.ai_text.ai_text as ai_text_mod

    def fake_generate_image(self, settings, device_config):
        return Image.new('RGB', device_config.get_resolution(), 'white')

    monkeypatch.setattr(ai_text_mod.AIText, 'generate_image', fake_generate_image, raising=True)

    # Prepare display manager with mock display
    from display.display_manager import DisplayManager
    dm = DisplayManager(device_config_dev)
    calls = {"display": 0}

    def fake_display_image(img, image_settings=None):
        calls["display"] += 1

    monkeypatch.setattr(dm, 'display_image', fake_display_image, raising=True)

    # Load plugins and simulate one interval cycle
    from plugins.plugin_registry import load_plugins, get_plugin_instance
    load_plugins(device_config_dev.get_plugins())

    from refresh_task import RefreshTask, PlaylistRefresh
    task = RefreshTask(device_config_dev, dm)

    # Force current time to 12:30 so P1 is active and has higher priority than Default
    import pytz
    tz = pytz.timezone(device_config_dev.get_config("timezone", default="UTC"))
    fixed_now = tz.localize(__import__('datetime').datetime(2025, 1, 1, 12, 30, 0))
    monkeypatch.setattr(task, '_get_current_datetime', lambda: fixed_now, raising=True)
    now = task._get_current_datetime()
    playlist, plugin_instance = task._determine_next_plugin(pm, device_config_dev.get_refresh_info(), now)
    assert plugin_instance is not None

    plugin_config = device_config_dev.get_plugin(plugin_instance.plugin_id)
    plugin = get_plugin_instance(plugin_config)

    action = PlaylistRefresh(playlist, plugin_instance)
    image = action.execute(plugin, device_config_dev, now)

    # Simulate display manager update path
    dm.display_image(image, image_settings=plugin.config.get("image_settings", []))

    assert calls["display"] == 1



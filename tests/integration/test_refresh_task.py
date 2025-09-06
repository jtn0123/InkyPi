# pyright: reportMissingImports=false
import os
from pathlib import Path
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import RefreshTask, ManualRefresh
from plugins.plugin_registry import load_plugins


def test_manual_update_triggers_display_and_refresh_info(device_config_dev, monkeypatch):
    # Ensure plugin registry is loaded
    load_plugins(device_config_dev.get_plugins())

    # Patch AI Text to avoid network calls
    import plugins.ai_text.ai_text as ai_text_mod

    def fake_generate_image(self, settings, device_config):
        return Image.new('RGB', device_config.get_resolution(), 'white')

    monkeypatch.setattr(ai_text_mod.AIText, 'generate_image', fake_generate_image, raising=True)

    display_manager = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, display_manager)

    try:
        task.start()

        # Manual update for ai_text
        os.environ['OPEN_AI_SECRET'] = 'test'
        settings = {'title': 'T', 'textModel': 'gpt-4o', 'textPrompt': 'Hi'}
        task.manual_update(ManualRefresh('ai_text', settings))

        # Validate current image saved
        assert Path(device_config_dev.current_image_file).exists()

        # Validate refresh info updated
        info = device_config_dev.get_refresh_info()
        assert info.plugin_id == 'ai_text'
        assert info.refresh_type == 'Manual Update'
        assert info.image_hash is not None
    finally:
        task.stop()



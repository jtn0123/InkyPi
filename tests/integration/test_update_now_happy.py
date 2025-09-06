# pyright: reportMissingImports=false
from PIL import Image


def test_update_now_happy_path(client, monkeypatch, flask_app):
    # Mock plugin image generation
    import plugins.ai_text.ai_text as ai_text_mod

    def fake_generate_image(self, settings, device_config):
        return Image.new('RGB', device_config.get_resolution(), 'white')

    monkeypatch.setattr(ai_text_mod.AIText, 'generate_image', fake_generate_image, raising=True)

    # Mock display
    called = {"displayed": False}

    def fake_display_image(image, image_settings=None):
        called["displayed"] = True

    display_manager = flask_app.config['DISPLAY_MANAGER']
    monkeypatch.setattr(display_manager, 'display_image', fake_display_image, raising=True)

    # Ensure background task is not running to use direct path
    refresh_task = flask_app.config['REFRESH_TASK']
    refresh_task.running = False

    resp = client.post('/update_now', data={
        'plugin_id': 'ai_text',
        'textPrompt': 'hello',
        'textModel': 'gpt-4o',
        'title': 'T'
    })
    assert resp.status_code == 200
    assert resp.json.get('success') is True
    assert called["displayed"] is True

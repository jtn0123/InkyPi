# pyright: reportMissingImports=false
import pytest
from unittest.mock import patch


def test_ai_text_generate_settings_template(monkeypatch, device_config_dev):
    from plugins.ai_text.ai_text import AIText

    plugin = AIText({"id": "ai_text"})
    template = plugin.generate_settings_template()

    assert "api_key" in template
    assert template["api_key"]["required"] is True
    assert template["api_key"]["service"] == "OpenAI"
    assert template["api_key"]["expected_key"] == "OPEN_AI_SECRET"
    assert template["style_settings"] is True


def test_ai_text_generate_image_missing_text_model(client, flask_app, monkeypatch):
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

    data = {
        "plugin_id": "ai_text",
        "title": "T",
        "textPrompt": "Hello",
        # Missing textModel
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 500
    assert b"Text Model is required" in resp.data


def test_ai_text_generate_image_missing_text_prompt(client, flask_app, monkeypatch):
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

    data = {
        "plugin_id": "ai_text",
        "title": "T",
        "textModel": "gpt-4o",
        "textPrompt": "",  # Empty prompt
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 500
    assert b"Text Prompt is required" in resp.data


@patch('plugins.ai_text.ai_text.OpenAI')
def test_ai_text_generate_image_openai_error(mock_openai, client, flask_app, monkeypatch):
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

    # Mock OpenAI to raise an exception
    mock_openai.side_effect = Exception("OpenAI API Error")

    data = {
        "plugin_id": "ai_text",
        "title": "T",
        "textModel": "gpt-4o",
        "textPrompt": "Hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 500
    assert b"Open AI request failure" in resp.data


@pytest.mark.parametrize("orientation,resolution", [("vertical", (400, 300)), ("horizontal", (800, 480))])
@patch('plugins.ai_text.ai_text.OpenAI')
def test_ai_text_generate_image_orientation(mock_openai, client, flask_app, monkeypatch, orientation, resolution):
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

    # Mock OpenAI chat completion
    class FakeMsg:
        def __init__(self, content):
            self.content = content

    class Choice:
        def __init__(self, content):
            self.message = FakeMsg(content)

    class FakeChat:
        def __init__(self):
            self.completions = self

        def create(self, *args, **kwargs):
            class Resp:
                choices = [Choice("Hello World")]

            return Resp()

    class FakeOpenAI:
        def __init__(self, api_key=None):
            self.chat = FakeChat()

    mock_openai.return_value = FakeOpenAI()

    # Mock orientation and resolution
    def mock_get_config(key):
        if key == "orientation":
            return orientation
        elif key == "resolution":
            return resolution
        return None

    monkeypatch.setattr(flask_app.config["DEVICE_CONFIG"], "get_config", mock_get_config)

    data = {
        "plugin_id": "ai_text",
        "title": "Welcome",
        "textModel": "gpt-4o",
        "textPrompt": "Say hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 200


def test_ai_text_generate_image_missing_key(client, flask_app, monkeypatch):
    # Ensure OPEN_AI_SECRET is not set
    import os

    if "OPEN_AI_SECRET" in os.environ:
        del os.environ["OPEN_AI_SECRET"]

    data = {
        "plugin_id": "ai_text",
        "title": "T",
        "textModel": "gpt-4o",
        "textPrompt": "Hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 500
    assert b"API Key not configured" in resp.data or b"Open AI" in resp.data


@patch('plugins.ai_text.ai_text.OpenAI')
def test_ai_text_generate_image_success(mock_openai, client, flask_app, monkeypatch):
    # Mock env key
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

    # Mock OpenAI chat completion
    class FakeMsg:
        def __init__(self, content):
            self.content = content

    class Choice:
        def __init__(self, content):
            self.message = FakeMsg(content)

    class FakeChat:
        def __init__(self):
            self.completions = self

        def create(self, *args, **kwargs):
            class Resp:
                choices = [Choice("Hello World")]

            return Resp()

    class FakeOpenAI:
        def __init__(self, api_key=None):
            self.chat = FakeChat()

    mock_openai.return_value = FakeOpenAI()

    # Post valid form
    data = {
        "plugin_id": "ai_text",
        "title": "Welcome",
        "textModel": "gpt-4o",
        "textPrompt": "Say hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 200

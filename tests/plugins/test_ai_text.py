# pyright: reportMissingImports=false
from unittest.mock import MagicMock, patch

import pytest


def test_ai_text_generate_settings_template(monkeypatch, device_config_dev):
    from plugins.ai_text.ai_text import AIText

    plugin = AIText({"id": "ai_text"})
    template = plugin.generate_settings_template()

    assert "api_key" in template
    assert template["api_key"]["required"] is True
    assert template["api_key"]["expected_key"] == "OPEN_AI_SECRET"
    assert template["api_key"]["alt_key"] == "GOOGLE_AI_SECRET"
    services = template["api_key"]["services"]
    assert [s["name"] for s in services] == ["OpenAI", "Google"]
    assert [s["env_var"] for s in services] == ["OPEN_AI_SECRET", "GOOGLE_AI_SECRET"]
    assert template["style_settings"] is True
    assert "settings_schema" in template


def test_ai_text_model_labels_show_input_and_output_prices(device_config_dev):
    """Regression for JTN-635: model labels must show both input AND output prices."""
    import re

    from plugins.ai_text.ai_text import AIText

    plugin = AIText({"id": "ai_text"})
    schema_dict = plugin.build_settings_schema()

    # Find the textModel field recursively
    def _find_field(node, name):
        if isinstance(node, dict):
            if node.get("name") == name:
                return node
            for v in node.values():
                found = _find_field(v, name)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for v in node:
                found = _find_field(v, name)
                if found is not None:
                    return found
        return None

    text_model_field = _find_field(schema_dict, "textModel")
    assert text_model_field is not None, "textModel field missing from schema"

    options_by_value = text_model_field.get("options_by_value") or {}
    assert "openai" in options_by_value
    assert "google" in options_by_value

    # Each label must include an input AND output price marker.
    label_re = re.compile(r"\$\d+(?:\.\d+)?\s*in\s*/\s*\$\d+(?:\.\d+)?\s*out", re.I)

    all_options = []
    for provider_opts in options_by_value.values():
        all_options.extend(provider_opts)

    assert all_options, "Expected at least one model option"
    for opt in all_options:
        label = opt.get("label", "")
        assert label_re.search(label), (
            f"Model label {label!r} must show both input and output prices "
            "(e.g. '$X in / $Y out per 1M')"
        )
        assert "in" in label.lower() and "out" in label.lower()


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
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "plugin_error"
    # JTN-326: plugin RuntimeError text is no longer surfaced by /update_now
    # (py/stack-trace-exposure).  Response is a generic message.
    assert body["error"] == "An internal error occurred"


def test_ai_text_generate_image_missing_text_prompt(client, flask_app, monkeypatch):
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

    data = {
        "plugin_id": "ai_text",
        "title": "T",
        "textModel": "gpt-5-nano",
        "textPrompt": "",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "plugin_error"
    # JTN-326: generic message only — the RuntimeError detail is logged.
    assert body["error"] == "An internal error occurred"


@patch("plugins.ai_text.ai_text.OpenAI")
def test_ai_text_generate_image_openai_error(
    mock_openai, client, flask_app, monkeypatch
):
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

    mock_openai.side_effect = Exception("OpenAI API Error")

    data = {
        "plugin_id": "ai_text",
        "title": "T",
        "textModel": "gpt-5-nano",
        "textPrompt": "Hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "plugin_error"
    # JTN-326: generic message only — upstream failure text is logged.
    assert body["error"] == "An internal error occurred"


@pytest.mark.parametrize(
    "orientation,resolution", [("vertical", (400, 300)), ("horizontal", (800, 480))]
)
@patch("plugins.ai_text.ai_text.OpenAI")
def test_ai_text_generate_image_orientation(
    mock_openai, client, flask_app, monkeypatch, orientation, resolution
):
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

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

    def mock_get_config(key, default=None):
        if key == "orientation":
            return orientation
        if key == "resolution":
            return resolution
        return default

    monkeypatch.setattr(
        flask_app.config["DEVICE_CONFIG"], "get_config", mock_get_config
    )

    data = {
        "plugin_id": "ai_text",
        "title": "Welcome",
        "textModel": "gpt-5-nano",
        "textPrompt": "Say hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 200


def test_ai_text_generate_image_missing_key(client, flask_app, monkeypatch):
    import os

    if "OPEN_AI_SECRET" in os.environ:
        del os.environ["OPEN_AI_SECRET"]

    data = {
        "plugin_id": "ai_text",
        "title": "T",
        "textModel": "gpt-5-nano",
        "textPrompt": "Hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "plugin_error"
    # JTN-326: RuntimeError text is no longer echoed (py/stack-trace-exposure).
    assert body["error"] == "An internal error occurred"


@patch("plugins.ai_text.ai_text.OpenAI")
def test_ai_text_generate_image_success(mock_openai, client, flask_app, monkeypatch):
    import os

    os.environ["OPEN_AI_SECRET"] = "test"

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

    data = {
        "plugin_id": "ai_text",
        "title": "Welcome",
        "textModel": "gpt-5-nano",
        "textPrompt": "Say hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 200


def test_ai_text_google_missing_key(device_config_dev):
    """Test ai_text plugin with missing Google API key."""
    from plugins.ai_text.ai_text import AIText

    plugin = AIText({"id": "ai_text"})
    settings = {
        "provider": "google",
        "textModel": "gemini-3-flash-preview",
        "textPrompt": "Hello",
    }

    with patch.object(device_config_dev, "load_env_key", lambda key: None):
        with pytest.raises(RuntimeError, match="Google AI API Key not configured"):
            plugin.generate_image(settings, device_config_dev)


def test_ai_text_google_success(device_config_dev, monkeypatch):
    """Test ai_text plugin with Google provider success."""
    import sys

    from plugins.ai_text.ai_text import AIText

    plugin = AIText({"id": "ai_text"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    # Build fake google.genai module hierarchy
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai

    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    mock_text_response = MagicMock()
    mock_text_response.text = "Generated text response"
    mock_client.models.generate_content.return_value = mock_text_response

    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", mock_genai.types)

    with patch.object(plugin, "render_image") as mock_render:
        mock_render.return_value = MagicMock()

        settings = {
            "provider": "google",
            "textModel": "gemini-3-flash-preview",
            "textPrompt": "Say hello",
            "title": "Test",
        }

        result = plugin.generate_image(settings, device_config_dev)

        mock_client.models.generate_content.assert_called_once()
        assert result is not None

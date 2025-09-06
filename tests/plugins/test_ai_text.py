# pyright: reportMissingImports=false


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


def test_ai_text_generate_image_success(client, flask_app, monkeypatch):
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

    import plugins.ai_text.ai_text as ai_text_mod

    monkeypatch.setattr(ai_text_mod, "OpenAI", FakeOpenAI, raising=True)

    # Post valid form
    data = {
        "plugin_id": "ai_text",
        "title": "Welcome",
        "textModel": "gpt-4o",
        "textPrompt": "Say hello",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 200

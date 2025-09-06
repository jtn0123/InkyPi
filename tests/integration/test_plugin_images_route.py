import os


def test_plugin_static_image_route(client):
    # Create a fake plugin asset
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "plugins")
    )
    plugin_dir = os.path.join(base, "ai_text")
    icon_src = os.path.join(plugin_dir, "icon.png")

    # Ensure icon exists in repo
    assert os.path.exists(icon_src), "Expected plugin icon to exist in repository"

    # Request through route
    resp = client.get("/images/ai_text/icon.png")
    assert resp.status_code == 200
    assert resp.data[:8] != b"", "Non-empty body"
    # Content-Type should be an image type
    assert "image" in (resp.headers.get("Content-Type") or "")

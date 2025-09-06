# pyright: reportMissingImports=false


def test_update_now_ai_text_missing_fields(client):
    resp = client.post("/update_now", data={"plugin_id": "ai_text"})
    assert resp.status_code == 500


def test_update_now_ai_image_missing_key(client):
    resp = client.post(
        "/update_now",
        data={
            "plugin_id": "ai_image",
            "textPrompt": "hi",
            "imageModel": "dall-e-2",
            "quality": "standard",
        },
    )
    assert resp.status_code == 500


def test_update_now_apod_missing_key(client):
    resp = client.post("/update_now", data={"plugin_id": "apod"})
    assert resp.status_code == 500

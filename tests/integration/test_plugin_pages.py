# pyright: reportMissingImports=false

def test_plugin_page_ai_text(client):
    resp = client.get('/plugin/ai_text')
    assert resp.status_code == 200
    assert b"AI Text" in resp.data


def test_plugin_page_ai_image(client):
    resp = client.get('/plugin/ai_image')
    assert resp.status_code == 200
    assert b"AI Image" in resp.data or b"Image Model" in resp.data


def test_plugin_page_apod(client):
    resp = client.get('/plugin/apod')
    assert resp.status_code == 200
    assert b"APOD" in resp.data or b"NASA" in resp.data



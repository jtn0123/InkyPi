# pyright: reportMissingImports=false
from io import BytesIO


def test_plugin_page_not_found(client):
    resp = client.get('/plugin/unknown')
    assert resp.status_code == 404


def test_delete_plugin_instance_missing(client):
    resp = client.post('/delete_plugin_instance', json={
        "playlist_name": "Default", "plugin_id": "x", "plugin_instance": "nope"
    })
    assert resp.status_code in (200, 400)


def test_update_plugin_instance_missing(client):
    resp = client.put('/update_plugin_instance/does-not-exist', data={"plugin_id": "ai_text"})
    assert resp.status_code in (200, 500)



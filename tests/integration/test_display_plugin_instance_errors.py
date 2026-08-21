from flask.testing import FlaskClient


def test_display_plugin_instance_missing_playlist(client: FlaskClient) -> None:
    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "DoesNotExist",
            "plugin_id": "ai_text",
            "plugin_instance": "default",
        },
    )
    assert resp.status_code in (200, 400)
    data = resp.get_json()
    assert data is not None
    assert data.get("success") in (False, None)

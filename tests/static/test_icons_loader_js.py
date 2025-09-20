"""Static checks for icons_loader.js no-op presence."""


def test_icons_loader_script_exists(client):
    resp = client.get("/static/scripts/icons_loader.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # It should be a no-op but present
    assert "no-op" in js or "no op" in js or "does nothing" in js


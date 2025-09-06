# pyright: reportMissingImports=false


def test_playlist_page_renders(client):
    resp = client.get("/playlist")
    assert resp.status_code == 200


def test_create_update_delete_playlist_flow(client):
    # Create
    payload = {"playlist_name": "Morning", "start_time": "06:00", "end_time": "09:00"}
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200

    # Update
    upd = {"new_name": "EarlyMorning", "start_time": "05:00", "end_time": "08:00"}
    resp = client.put("/update_playlist/Morning", json=upd)
    assert resp.status_code == 200

    # Delete
    resp = client.delete("/delete_playlist/EarlyMorning")
    assert resp.status_code == 200


def test_add_plugin_to_playlist_validation(client):
    # Missing fields
    resp = client.post("/add_plugin", data={})
    assert resp.status_code == 500 or resp.status_code == 400

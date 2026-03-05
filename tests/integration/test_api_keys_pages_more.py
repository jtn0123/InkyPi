def test_generic_api_keys_page_uses_canonical_template(client):
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="themeToggle"' in html
    assert "API Keys" in html
    assert "Add API Key" in html

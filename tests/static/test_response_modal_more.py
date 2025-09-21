def test_handle_json_response_presence(client):
    resp = client.get("/static/scripts/response_modal.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Check that handleJsonResponse includes request_id and maps codes
    assert "handleJsonResponse" in js
    assert "request_id" in js
    assert "getErrorMessage" in js
    # Common messages present
    assert "Server error" in js
    assert "Resource not found" in js or "Not found" in js


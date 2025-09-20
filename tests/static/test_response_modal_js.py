"""Static checks for response_modal.js presence and key APIs."""


def test_response_modal_script_exists(client):
    resp = client.get("/static/scripts/response_modal.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Core functions
    for token in [
        "function ensureToastContainer()",
        "function showToast(status, message, duration = 5000)",
        "function closeToast(toastId)",
        "function showResponseModal(status, message, useToast = true)",
        "function closeResponseModal()",
        "async function handleJsonResponse(response, options = {})",
        "function getErrorMessage(status)",
        "function showSuccess(message, duration)",
        "function showError(message, duration)",
        "function showWarning(message, duration)",
        "function showInfo(message, duration)",
    ]:
        assert token in js


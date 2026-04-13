# pyright: reportMissingImports=false

import json


def test_update_now_metrics_format(client):
    """Test that /update_now returns metrics with steps in the correct format.

    This test ensures that the steps array contains objects with 'name' and 'elapsed_ms'
    properties, not arrays. This prevents the frontend destructuring error where it expects
    [name, ms] tuples but receives {name: ..., elapsed_ms: ...} objects.

    Regression test for: Frontend error "An error occurred..." when AI image generation succeeds
    """
    # Make request to a simple plugin (clock doesn't require API keys)
    resp = client.post(
        "/update_now",
        data={"plugin_id": "clock"},
    )

    # Should succeed and return metrics
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["success"] is True
    assert "metrics" in data

    # Verify steps format
    metrics = data["metrics"]
    assert "steps" in metrics
    assert isinstance(metrics["steps"], list)

    # Each step should be an object with 'name' and 'elapsed_ms' properties
    # NOT an array like [name, elapsed_ms]
    if metrics["steps"]:  # Only check if steps exist
        for step in metrics["steps"]:
            assert isinstance(step, dict), f"Step should be object, got {type(step)}"
            assert "name" in step, "Step should have 'name' property"
            assert "elapsed_ms" in step, "Step should have 'elapsed_ms' property"
            assert isinstance(step["name"], str)
            assert isinstance(step["elapsed_ms"], int)


def test_update_now_ai_text_missing_fields(client):
    resp = client.post("/update_now", data={"plugin_id": "ai_text"})
    assert resp.status_code == 400


def test_update_now_ai_image_missing_key(client):
    resp = client.post(
        "/update_now",
        data={
            "plugin_id": "ai_image",
            "textPrompt": "hi",
            "imageModel": "gpt-image-1.5",
            "quality": "standard",
        },
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == "plugin_error"
    # JTN-326: plugin RuntimeError text is no longer echoed — the response is
    # a generic message (py/stack-trace-exposure).  The actual reason is logged.
    assert "API Key" not in body["error"]
    assert body["error"] == "An internal error occurred"


def test_update_now_apod_missing_key(client):
    resp = client.post("/update_now", data={"plugin_id": "apod"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == "plugin_error"
    # JTN-326: generic error — exception text is no longer exposed.
    assert body["error"] == "An internal error occurred"
    assert "NASA" not in body["error"]


def test_update_now_returns_generic_error_for_missing_key(client):
    """JTN-326: /update_now must return a generic error, not the plugin
    exception text (py/stack-trace-exposure, plugin.py:705)."""
    resp = client.post("/update_now", data={"plugin_id": "apod"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "An internal error occurred"
    assert body["code"] == "plugin_error"
    # No fragment of the underlying RuntimeError leaks to the client.
    assert "API Key" not in body["error"]
    assert "NASA" not in body["error"]

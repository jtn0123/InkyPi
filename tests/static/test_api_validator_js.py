"""Static checks for api_validator.js presence and key APIs."""


def test_api_validator_script_exists(client):
    resp = client.get("/static/scripts/api_validator.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Classes exposed
    assert "class APIValidator" in js
    assert "class APIValidationUI" in js
    assert "window.APIValidator" in js
    assert "window.APIValidationUI" in js

    # Core methods on APIValidator
    for token in [
        "async validateEndpoint(url, options = {})",
        "async _performValidation(url, options)",
        "_categorizeError(error)",
        "async validateMultiple(endpoints)",
        "clearCache()",
        "getCachedResult(url)",
    ]:
        assert token in js

    # UI helper methods
    for token in [
        "createValidationIndicator(input, options = {})",
        "async validateInput(input, indicator, options = {})",
        "updateIndicator(indicator, status, text)",
        "showValidationDetails(indicator, result)",
        "validateNow(input)",
        "addValidationToInputs(selector, options = {})",
    ]:
        assert token in js


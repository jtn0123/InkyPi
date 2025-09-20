"""Static checks for enhanced_progress.js presence and key APIs."""


def test_enhanced_progress_script_exists(client):
    resp = client.get("/static/scripts/enhanced_progress.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Class and globals
    assert "class EnhancedProgressDisplay" in js
    assert "window.EnhancedProgressDisplay" in js
    assert "window.createEnhancedProgress" in js

    # Core methods
    for token in [
        "initializeElements()",
        "start(steps = [], title = 'Processing...')",
        "nextStep(description = '', substeps = [])",
        "updateStep(stepName, description = '', progress = 0, substeps = [])",
        "updateProgress(progress)",
        "complete(message = 'Operation completed', success = true)",
        "fail(error = 'Operation failed')",
        "renderSteps()",
        "updateStepVisual(stepIndex)",
        "getTimingSummary()",
    ]:
        assert token in js

    # Key UI elements rendered
    assert "enhanced-progress-header" in js
    assert "enhanced-progress-fill" in js
    assert "enhanced-progress-steps" in js
    assert "enhanced-progress-log" in js


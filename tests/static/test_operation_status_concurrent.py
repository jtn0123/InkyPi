"""Tests for operation_status.js concurrent form submission fix.

JTN-260: Concurrent form submissions shared mutable fetch-wrapper state
(fetchWrapped, fetchTimeoutId) at module level.  If form A submitted and
then form B submitted before A's response arrived, B's operation was never
completed because the `if (!fetchWrapped)` guard prevented B from wrapping
fetch.

Fix: each submit handler now uses its own per-operation closure variables
(operationCompleted, localTimeoutId, previousFetch) and installs its own
wrappedFetch on top of whatever window.fetch is current, forming a chain.
"""


def test_operation_status_script_exists(client):
    resp = client.get("/static/scripts/operation_status.js")
    assert resp.status_code == 200


def test_no_shared_fetchWrapped_state(client):
    """JTN-260: The module-level shared fetchWrapped flag must not exist.

    The bug was caused by a single let fetchWrapped = false declared outside
    the submit handler.  After the fix that variable is gone; each operation
    uses its own per-closure state instead.
    """
    resp = client.get("/static/scripts/operation_status.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # The shared flag must not appear at module/DOMContentLoaded level
    assert "let fetchWrapped = false;" not in js
    assert "fetchWrapped = true;" not in js
    assert "if (!fetchWrapped)" not in js


def test_no_shared_fetchTimeoutId_state(client):
    """JTN-260: The module-level fetchTimeoutId must not exist.

    Previously a single fetchTimeoutId was shared across all concurrent
    submissions; the second submission would clear the first submission's
    timeout.  After the fix, each operation uses localTimeoutId.
    """
    resp = client.get("/static/scripts/operation_status.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "let fetchTimeoutId = null;" not in js
    # fetchTimeoutId should not appear at all; localTimeoutId is used instead
    assert "fetchTimeoutId" not in js


def test_per_operation_local_timeout_id(client):
    """JTN-260: Each operation must declare its own localTimeoutId."""
    resp = client.get("/static/scripts/operation_status.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "let localTimeoutId = null;" in js
    assert "localTimeoutId = setTimeout(" in js
    assert "clearTimeout(localTimeoutId)" in js


def test_per_operation_previous_fetch_captured(client):
    """JTN-260: Each submit handler must capture the current window.fetch before
    installing its own wrapper, enabling safe stacking when multiple operations
    are in flight concurrently.
    """
    resp = client.get("/static/scripts/operation_status.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # previousFetch captures whatever window.fetch is at submission time
    assert "const previousFetch = window.fetch;" in js
    # The wrapper must delegate to previousFetch, not nativeFetch directly
    assert "return previousFetch(...args)" in js


def test_wrapped_fetch_installed_unconditionally(client):
    """JTN-260: Every submit must install its own wrapper without a guard.

    The old guard `if (!fetchWrapped)` prevented the second concurrent
    submission from installing its wrapper.  The fix removes the guard so
    every submission installs wrappedFetch unconditionally.
    """
    resp = client.get("/static/scripts/operation_status.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # wrappedFetch function must be defined inside the submit handler
    assert "function wrappedFetch(" in js
    # It must be installed on window.fetch
    assert "window.fetch = wrappedFetch;" in js


def test_finish_operation_restores_previous_fetch(client):
    """JTN-260: finishOperation must restore previousFetch, not nativeFetch.

    Restoring nativeFetch (the original pre-page-load fetch) would silently
    discard any wrappers installed by other in-flight operations.  Restoring
    previousFetch correctly unwinds only the layer added by this operation.
    """
    resp = client.get("/static/scripts/operation_status.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "window.fetch = previousFetch;" in js
    # The restore must be guarded so only the active wrapper is removed
    assert "if (window.fetch === wrappedFetch)" in js

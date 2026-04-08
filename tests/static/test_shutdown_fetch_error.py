"""Test that handleShutdown wraps fetch in try/catch (JTN-247).

The device severs the connection on shutdown/reboot, causing fetch to throw a
TypeError.  Without a try/catch this surfaces as a confusing error modal after
the success message has already been shown.
"""

from pathlib import Path


def test_handle_shutdown_fetch_wrapped_in_try_catch():
    """handleShutdown must catch network errors from fetch so the device
    going offline doesn't show an error after the success modal."""
    js = Path("src/static/scripts/settings_page.js").read_text()

    # Locate the handleShutdown function
    assert "async function handleShutdown" in js, "handleShutdown function not found"

    # The fetch call inside handleShutdown must be inside a try block
    assert "try {" in js, "try block not found in settings_page.js"

    # There must be a catch clause that ignores the error
    assert "} catch (e) {" in js, "catch clause not found"

    # Verify the comment explaining *why* the error is silenced is present
    assert "shutting down" in js, "explanatory comment about shutdown not found"

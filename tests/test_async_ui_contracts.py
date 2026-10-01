"""Execute shipped page scripts at their asynchronous event boundaries."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["dashboard", "plugin-action", "plugin-instance"])
def test_async_refresh_failure_has_feedback_without_unhandled_rejection(
    scenario: str,
) -> None:
    node = shutil.which("node")
    assert node is not None, "Node is required to execute page JavaScript"
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            node,
            str(root / "tests/fixtures/async_refresh_probe.js"),
            scenario,
            str(root),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr

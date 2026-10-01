"""Execute dashboard data and lifecycle contracts against the shipped script."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "scenario",
    [
        "initial",
        "event:refresh_started",
        "event:refresh_complete",
        "event:plugin_failed",
        "event:message",
        "reconnect",
        "polling",
        "fallback",
        "http",
        "network",
        "partial-current",
        "partial-next",
        "recovery",
        "empty-success",
        "race-preview",
        "race-warning",
        "race-kpis",
        "race-kpi-warning",
        "kpi-partial",
        "kpi-partial-health",
        "kpi-unavailable",
    ],
)
def test_dashboard_reliability(scenario: str) -> None:
    node = shutil.which("node")
    assert node is not None, "Node is required to execute shipped dashboard JavaScript"
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            node,
            str(root / "tests/fixtures/dashboard_reliability_probe.js"),
            scenario,
            str(root / "src/static/scripts/dashboard_page.js"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr

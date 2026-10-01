"""Exercise the installer commands shipped in release and simulator workflows."""

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("source", ["release", "simulator"])
def test_workflow_invokes_non_executable_installer(tmp_path: Path, source: str) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("#!/bin/bash\nprintf 'installer reached\\n'\n")
    installer.chmod(0o644)
    if source == "release":
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/build-pi-image.yml").read_text()
        )
        steps = workflow["jobs"]["build-image"]["steps"]
        step = next(s for s in steps if s["name"].startswith("Run install.sh"))
        command = next(
            line.strip()
            for line in step["run"].splitlines()
            if re.fullmatch(r"\s*(?:bash )?\./install\.sh\s*", line)
        )
    else:
        dockerfile = (ROOT / "scripts/Dockerfile.sim-install").read_text()
        cmd = next(
            line.removeprefix("CMD ")
            for line in dockerfile.splitlines()
            if line.startswith("CMD ")
        )
        command = json.loads(cmd)[-1].split("&&", 1)[1].strip()
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "installer reached\n"

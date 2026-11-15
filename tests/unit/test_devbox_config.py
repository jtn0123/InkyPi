"""`devbox run test` goes through scripts/test.sh, like every other entry point.

A bare `pytest` skipped the environment check and the memory-test split that
scripts/test-fast.sh does; running the whole suite that way has run a Mac out
of memory.
"""

from __future__ import annotations

import re
from pathlib import Path

DEVBOX = Path(__file__).resolve().parents[2] / "devbox.json"


def test_devbox_test_script_uses_the_project_runner() -> None:
    # devbox.json is JSONC (comments, trailing commas), so read the block.
    block = re.search(r'"test":\s*\[(.*?)\]', DEVBOX.read_text(), re.DOTALL)
    assert block, "devbox.json has no `test` script"
    commands = [c for c in re.findall(r'"([^"]*)"', block.group(1)) if c]
    assert commands == ["bash scripts/test.sh"], commands

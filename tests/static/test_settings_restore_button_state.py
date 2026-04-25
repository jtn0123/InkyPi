"""Regression guards for the Restore-from-file button (`#importConfigBtn`).

Background: an earlier version of `importConfig` flipped the button to
`disabled=true` and `textContent="Restoring…"` *before* checking whether
a file was attached. If the user clicked the button without a file, the
function showed an error toast and returned — leaving the button stuck in
the disabled "Restoring…" state until the user re-picked a file. The
fix is to validate the file *first*, then disable + relabel the button only
on the path that actually goes to the network. This test guards against
regression by checking the source structure.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIONS_JS = ROOT / "src" / "static" / "scripts" / "settings" / "actions.js"


def _import_config_body() -> str:
    """Return the JS source text of `async function importConfig() { ... }`.

    Uses brace counting rather than a hard-coded ``\\n {4}\\}\\n`` tail so
    the test isn't coupled to the formatter's chosen indentation or to the
    presence of a trailing newline. Skips braces inside `'…'`, `"…"`, and
    template strings ``…`` so embedded ``{`` / ``}`` literals don't throw
    the depth counter off.
    """
    src = ACTIONS_JS.read_text(encoding="utf-8")
    head = re.search(r"async function importConfig\(\)\s*\{", src)
    assert head, "importConfig function not found in actions.js"
    i = head.end()  # cursor sits just past the opening `{`
    depth = 1
    in_str: str | None = None  # which quote char are we inside, if any
    escape = False
    body_start = i
    while i < len(src) and depth > 0:
        ch = src[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
        elif ch in ("'", '"', "`"):
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[body_start:i]
        i += 1
    raise AssertionError("unbalanced braces in importConfig — could not find end")


def test_import_config_validates_file_before_disabling_button():
    """The 'no file' early-return must run *before* the button is flipped to
    `disabled` + `Restoring…`, otherwise the button stays stuck on the
    failure path."""
    body = _import_config_body()
    file_check_pos = body.find('"Choose a backup file first"')
    relabel_pos = body.find('"Restoring')
    assert (
        file_check_pos != -1
    ), "missing-file early return is gone — restoring it is the whole point of this test"
    assert relabel_pos != -1, '"Restoring..." label not found in importConfig'
    assert file_check_pos < relabel_pos, (
        f"file-presence check (pos {file_check_pos}) must run BEFORE the "
        f"button is disabled with 'Restoring…' (pos {relabel_pos}); "
        "otherwise the button gets stuck on the early-return path."
    )


def test_import_config_finally_block_restores_label_and_disabled_state():
    """The finally block must restore the button text and reflect the
    file-input state (disabled iff no file selected). It must not leave the
    button stuck on "Restoring…"."""
    body = _import_config_body()
    finally_match = re.search(r"finally\s*\{(?P<finally>.*?)\}\s*$", body, flags=re.S)
    assert finally_match, "importConfig has no finally block"
    finally_body = finally_match.group("finally")
    assert (
        '"Restore from file"' in finally_body
    ), "finally must reset the button label to 'Restore from file'"
    assert (
        "fileInput?.files?.length" in finally_body or "files?.length" in finally_body
    ), "finally must re-derive the disabled state from the current file input"

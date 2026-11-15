"""Page scripts ask and report in the app's own dialogs and toasts.

``alert``/``confirm``/``prompt`` ignore the theme, block the page, and are
answered "no" without being shown in headless browsers, so a browser test
cannot reach what comes after them.
"""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "static" / "scripts"
_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\"'])//[^\n]*", re.S)
_NATIVE = re.compile(
    r"(?:(?<![\w$.])|\b(?:window|globalThis|self)\s*\.\s*)(alert|confirm|prompt)\s*\("
)
_METHOD_DEFINITION = re.compile(
    r"^\s*(?:async\s+)?(alert|confirm|prompt)\s*\([^)]*\)\s*\{"
)


def _native_dialog_calls(source: str) -> list[str]:
    code = _COMMENT.sub("", source)
    calls: list[str] = []
    for line in code.splitlines():
        if _METHOD_DEFINITION.match(line):
            continue
        calls.extend(m.group(0) for m in _NATIVE.finditer(line))
    return calls


def test_page_scripts_do_not_use_native_dialogs() -> None:
    offenders = {
        str(path.relative_to(SCRIPTS)): calls
        for path in sorted(SCRIPTS.rglob("*.js"))
        if (calls := _native_dialog_calls(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_the_scan_finds_native_dialogs() -> None:
    assert _native_dialog_calls("if (!confirm(`Delete?`)) return;") == ["confirm("]
    assert _native_dialog_calls("window.alert(err);") == ["window.alert("]
    assert _native_dialog_calls("globalThis . prompt('name')") == [
        "globalThis . prompt("
    ]


def test_the_scan_ignores_comments_methods_and_other_objects() -> None:
    source = """
    // not window.confirm(): it ignores the theme
    /* alert(1) */
    modal.confirm(true);
    async confirm(answer) {
    const url = "https://example.com"; // confirm(
    """
    assert _native_dialog_calls(source) == []

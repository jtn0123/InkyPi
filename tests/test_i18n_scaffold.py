"""Tests for the i18n scaffolding (JTN-459).

Covers:
- _() returns msg unchanged (identity function for "en")
- extract_strings finds known strings in fixture templates
- extract_strings --check passes when extracted.json is up to date
- extract_strings --check fails when extracted.json is stale
- Jinja template using {{ _('hello') }} renders 'hello'
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


# ---------------------------------------------------------------------------
# 1.  _() identity function
# ---------------------------------------------------------------------------


def test_underscore_returns_msg_unchanged():
    from utils.i18n import _

    assert _("Settings") == "Settings"
    assert _("Hello, world!") == "Hello, world!"
    assert _("") == ""
    assert _("untranslated key xyz") == "untranslated key xyz"


def test_underscore_returns_string_type():
    from utils.i18n import _

    result = _("any key")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 2.  extract_strings finds known strings in fixture templates
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_template_dir(tmp_path: Path) -> Path:
    """Create a small tree of fixture files containing _() calls."""
    tmpl_dir = tmp_path / "templates"
    tmpl_dir.mkdir()

    (tmpl_dir / "page.html").write_text(
        '{{ _("Save") }}\n{{ _("Cancel") }}\n{{ _("Settings") }}\n',
        encoding="utf-8",
    )
    (tmpl_dir / "sub").mkdir(exist_ok=True)
    (tmpl_dir / "sub" / "widget.html").write_text(
        '{% set label = _("Delete") %}\n',
        encoding="utf-8",
    )

    py_dir = tmp_path / "src"
    py_dir.mkdir()
    (py_dir / "helper.py").write_text(
        'msg = _("Upload")\nother = _("Download")\n',
        encoding="utf-8",
    )

    return tmp_path


def _run_extractor(argv: list[str]) -> int:
    """Import and call extract_strings.main() with *argv*."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))

    import importlib

    spec = importlib.util.spec_from_file_location(
        "extract_strings", SCRIPTS_DIR / "extract_strings.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod.main(argv)


def test_extract_strings_finds_strings_in_fixtures(
    fixture_template_dir: Path, tmp_path: Path
):
    output_path = tmp_path / "out.json"
    # Point --src at the fixture tree (both templates/ and src/ are inside it)
    rc = _run_extractor(
        ["--src", str(fixture_template_dir), "--output", str(output_path)]
    )
    assert rc == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    strings = data["strings"]

    assert "Save" in strings
    assert "Cancel" in strings
    assert "Settings" in strings
    assert "Delete" in strings
    assert "Upload" in strings
    assert "Download" in strings


def test_extract_strings_output_is_sorted(fixture_template_dir: Path, tmp_path: Path):
    output_path = tmp_path / "out.json"
    _run_extractor(["--src", str(fixture_template_dir), "--output", str(output_path)])
    data = json.loads(output_path.read_text(encoding="utf-8"))
    strings = data["strings"]
    assert strings == sorted(strings)


# ---------------------------------------------------------------------------
# 3.  --check passes when extracted.json matches current extraction
# ---------------------------------------------------------------------------


def test_extract_strings_check_passes_when_up_to_date(
    fixture_template_dir: Path, tmp_path: Path
):
    output_path = tmp_path / "out.json"
    # First run: write the catalogue.
    rc = _run_extractor(
        ["--src", str(fixture_template_dir), "--output", str(output_path)]
    )
    assert rc == 0

    # Second run with --check: should pass.
    rc = _run_extractor(
        ["--src", str(fixture_template_dir), "--output", str(output_path), "--check"]
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# 4.  --check fails when extracted.json is stale
# ---------------------------------------------------------------------------


def test_extract_strings_check_fails_when_stale(
    fixture_template_dir: Path, tmp_path: Path
):
    output_path = tmp_path / "out.json"
    # Write a stale catalogue (missing strings present in the fixture).
    stale = {"_meta": {"description": "stale"}, "strings": ["OldString"]}
    output_path.write_text(json.dumps(stale), encoding="utf-8")

    rc = _run_extractor(
        ["--src", str(fixture_template_dir), "--output", str(output_path), "--check"]
    )
    assert rc == 1


def test_extract_strings_check_fails_when_file_missing(
    fixture_template_dir: Path, tmp_path: Path
):
    output_path = tmp_path / "nonexistent.json"
    rc = _run_extractor(
        ["--src", str(fixture_template_dir), "--output", str(output_path), "--check"]
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# 5.  Jinja template using {{ _('hello') }} renders 'hello'
# ---------------------------------------------------------------------------


def test_jinja_template_renders_with_underscore():
    from flask import Flask

    from utils.i18n import init_i18n

    test_app = Flask(__name__)
    init_i18n(test_app)

    with test_app.app_context():
        rendered = test_app.jinja_env.from_string("{{ _('hello') }}").render()
        assert rendered == "hello"

    with test_app.app_context():
        rendered = test_app.jinja_env.from_string("{{ _('Settings') }}").render()
        assert rendered == "Settings"


def test_jinja_template_renders_unknown_key_as_key():
    from flask import Flask

    from utils.i18n import init_i18n

    test_app = Flask(__name__)
    init_i18n(test_app)

    with test_app.app_context():
        rendered = test_app.jinja_env.from_string(
            "{{ _('this key does not exist') }}"
        ).render()
        assert rendered == "this key does not exist"


# ---------------------------------------------------------------------------
# 6.  init_i18n with unsupported locale falls back to 'en' gracefully
# ---------------------------------------------------------------------------


def test_init_i18n_unsupported_locale_falls_back(monkeypatch):
    monkeypatch.setenv("INKYPI_LOCALE", "zz")

    from flask import Flask

    import utils.i18n as i18n_mod

    test_app = Flask(__name__)
    i18n_mod.init_i18n(test_app)

    # After fallback to 'en', _() still works as identity.
    assert i18n_mod._("Settings") == "Settings"


# ---------------------------------------------------------------------------
# 7.  translations/en/messages.json baseline integrity
# ---------------------------------------------------------------------------


def test_baseline_messages_json_is_valid():
    path = REPO_ROOT / "translations" / "en" / "messages.json"
    assert path.exists(), "translations/en/messages.json is missing"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)

    # Must have a _meta key
    assert "_meta" in data

    # All non-meta values must be strings
    for key, value in data.items():
        if key == "_meta":
            continue
        assert isinstance(key, str), f"Non-string key: {key!r}"
        assert isinstance(value, str), f"Non-string value for {key!r}: {value!r}"


def test_baseline_messages_json_has_minimum_strings():
    path = REPO_ROOT / "translations" / "en" / "messages.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    strings = {k: v for k, v in data.items() if not k.startswith("_")}
    assert (
        len(strings) >= 20
    ), f"Expected at least 20 baseline strings, got {len(strings)}"

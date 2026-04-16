from pathlib import Path


def test_duplicate_preset_focuses_value_input_first():
    js = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "api_keys_page.js"
    ).read_text(encoding="utf-8")

    assert 'const valueInput = existingRow.querySelector(".apikey-value");' in js
    assert '(valueInput || existingRow.querySelector(".apikey-key"))?.focus();' in js

import re
from pathlib import Path


def test_duplicate_preset_focuses_value_input_first():
    js = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "api_keys_page.js"
    ).read_text(encoding="utf-8")

    pattern = re.compile(
        r'querySelector\(\s*["\']\.apikey-value["\']\s*\)[\s\S]{0,200}?'
        r'querySelector\(\s*["\']\.apikey-key["\']\s*\)[\s\S]{0,80}?\.focus\(\)'
    )
    assert pattern.search(js), (
        "duplicate-preset focus should prefer .apikey-value over .apikey-key"
    )

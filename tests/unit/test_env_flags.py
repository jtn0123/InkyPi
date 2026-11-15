"""Every on/off environment variable is read by one helper.

The copies disagreed: ``on`` switched INKYPI_HTTP_LOG_LATENCY on but left
INKYPI_FORCE_HTTPS, INKYPI_SECURE_COOKIES and INKYPI_CSP_REPORT_ONLY off.
"""

from __future__ import annotations

import pytest
from flask import Flask

from utils.env_flags import env_bool

FLAG = "INKYPI_TEST_FLAG"


@pytest.mark.parametrize("default", [False, True])
def test_unset_gives_the_default(
    monkeypatch: pytest.MonkeyPatch, default: bool
) -> None:
    monkeypatch.delenv(FLAG, raising=False)
    assert env_bool(FLAG, default=default) is default


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " on ", "On"])
def test_truthy_values_switch_it_on(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(FLAG, value)
    assert env_bool(FLAG) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "enabled"])
def test_any_other_set_value_switches_it_off(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(FLAG, value)
    assert env_bool(FLAG, default=True) is False


def test_on_now_works_for_secure_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    from app_setup.security_middleware import setup_https_redirect

    monkeypatch.delenv("INKYPI_FORCE_HTTPS", raising=False)
    monkeypatch.setenv("INKYPI_SECURE_COOKIES", "on")
    app = Flask(__name__)

    setup_https_redirect(app, dev_mode=False)

    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_no_module_keeps_its_own_truthy_set() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if path.name != "env_flags.py"
        and ("_TRUTHY =" in path.read_text() or "def _env_bool" in path.read_text())
    ]
    assert offenders == []

"""Tests for i18n module accessors and reset_for_tests()."""

import pytest

import utils.i18n as i18n_mod
from utils.i18n import (
    _,
    get_active_locale,
    get_translations,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def reset_i18n():
    """Ensure clean i18n state before and after each test."""
    reset_for_tests()
    yield
    reset_for_tests()


def test_get_translations_returns_dict():
    """get_translations() returns a dict."""
    result = get_translations()
    assert isinstance(result, dict)


def test_get_active_locale_returns_default_en():
    """get_active_locale() returns 'en' before any init_i18n() call."""
    assert get_active_locale() == "en"


def test_identity_translation():
    """_() returns the key unchanged when no translations are loaded."""
    assert _("Settings") == "Settings"
    assert _("Hello World") == "Hello World"


def test_get_translations_reflects_state():
    """get_translations() reflects the current _TRANSLATIONS module global."""
    assert get_translations() is i18n_mod._TRANSLATIONS


def test_get_active_locale_reflects_state():
    """get_active_locale() reflects the current _ACTIVE_LOCALE module global."""
    assert get_active_locale() == i18n_mod._ACTIVE_LOCALE


def test_reset_for_tests_clears_translations():
    """reset_for_tests() resets _TRANSLATIONS to empty dict."""
    i18n_mod._TRANSLATIONS = {"Hello": "Hola"}
    reset_for_tests()
    assert i18n_mod._TRANSLATIONS == {}


def test_reset_for_tests_resets_locale():
    """reset_for_tests() resets _ACTIVE_LOCALE to 'en'."""
    i18n_mod._ACTIVE_LOCALE = "fr"
    reset_for_tests()
    assert i18n_mod._ACTIVE_LOCALE == "en"


def test_reset_for_tests_idempotent():
    """Calling reset_for_tests() twice does not raise."""
    reset_for_tests()
    reset_for_tests()
    assert get_active_locale() == "en"
    assert get_translations() == {}

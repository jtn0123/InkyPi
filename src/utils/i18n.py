"""
i18n.py — Internationalisation scaffolding for InkyPi.

This module provides gettext-style stubs that keep the runtime dependency-free
(stdlib only). The public API is intentionally minimal so that a future PR can
swap in a real gettext/fluent backend without touching templates or call-sites:

    from utils.i18n import _           # in Python source
    {{ _("Settings") }}               # in Jinja templates (after init_i18n)

Locale loading
--------------
The active locale is read from the ``INKYPI_LOCALE`` environment variable at
startup.  Currently only "en" is supported; unknown locales silently fall back
to identity (the key is returned unchanged).

Future work
-----------
* Load translations/XX/messages.json for locale XX at startup.
* Expose a ``set_locale(code)`` helper for runtime switching.
* Wire request-level locale detection from Accept-Language header.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_TRANSLATIONS: dict[str, str] = {}
_ACTIVE_LOCALE: str = "en"

_SUPPORTED_LOCALES = frozenset({"en"})


def _load_locale(locale: str) -> dict[str, str]:
    """Load messages.json for *locale* from the translations directory.

    Returns an empty dict if the file does not exist or cannot be parsed,
    so callers always get a safe mapping.
    """
    translations_dir = os.path.join(
        os.path.dirname(__file__),  # src/utils/
        "..",  # src/
        "..",  # repo root
        "translations",
        locale,
        "messages.json",
    )
    path = os.path.normpath(translations_dir)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logger.warning("i18n: %s does not contain a JSON object — ignored", path)
            return {}
        # Strip the internal _meta key if present.
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except FileNotFoundError:
        logger.debug("i18n: no translation file found at %s", path)
        return {}
    except Exception:
        logger.exception("i18n: failed to load %s", path)
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_translations() -> dict[str, str]:
    """Return the currently loaded translations mapping.

    Provides controlled read access to the module-level ``_TRANSLATIONS``
    dict so callers do not need to import the bare global directly.
    """
    return _TRANSLATIONS


def get_active_locale() -> str:
    """Return the currently active locale code (e.g. ``"en"``).

    Provides controlled read access to the module-level ``_ACTIVE_LOCALE``
    variable so callers do not need to import the bare global directly.
    """
    return _ACTIVE_LOCALE


def reset_for_tests() -> None:
    """Reset i18n state to defaults (testing only).

    Resets ``_TRANSLATIONS`` to an empty dict and ``_ACTIVE_LOCALE`` to
    ``"en"`` so that tests which call ``init_i18n()`` or inspect locale state
    do not affect one another.
    """
    global _TRANSLATIONS, _ACTIVE_LOCALE
    _TRANSLATIONS = {}
    _ACTIVE_LOCALE = "en"


def _(msg: str) -> str:
    """Return the localised form of *msg*, or *msg* itself if not found.

    This is an identity function for the "en" baseline and for any string not
    present in the loaded translation table.
    """
    return _TRANSLATIONS.get(msg, msg)


def init_i18n(app: Flask) -> None:
    """Initialise i18n and register ``_`` as a Jinja2 global on *app*.

    Call this once during application factory setup, e.g. in ``create_app()``.
    The locale is determined by the ``INKYPI_LOCALE`` environment variable
    (defaults to ``"en"``).
    """
    global _TRANSLATIONS, _ACTIVE_LOCALE

    requested = os.getenv("INKYPI_LOCALE", "en").strip().lower()
    if requested not in _SUPPORTED_LOCALES:
        logger.warning(
            "i18n: locale %r is not supported — falling back to 'en'", requested
        )
        requested = "en"

    _ACTIVE_LOCALE = requested
    _TRANSLATIONS = _load_locale(_ACTIVE_LOCALE)
    logger.info(
        "i18n: loaded locale %r (%d strings)", _ACTIVE_LOCALE, len(_TRANSLATIONS)
    )

    # Register as a Jinja2 global so templates can call {{ _(key) }} directly.
    app.jinja_env.globals["_"] = _

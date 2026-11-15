"""The environment a headless browser gets: enough to run, and no secrets.

The app's own environment can hold secrets (a systemd drop-in such as the
PIN, a developer's shell), and a child process inherits all of it by default.
Local renders run Chromium on plugin HTML with web security turned off, so
Chromium gets an allowlisted environment instead of the app's.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# What Chromium and the libraries it loads (fontconfig, ICU, the Debian
# wrapper script) read. Nothing here holds a credential.
_PASS_THROUGH = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LANGUAGE",
        "TZ",
        "SYSTEMROOT",
        "LD_LIBRARY_PATH",
        "CHROMIUM_FLAGS",
        "FONTCONFIG_FILE",
        "FONTCONFIG_PATH",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_DIRS",
        "XDG_RUNTIME_DIR",
    }
)
_PASS_THROUGH_PREFIXES = ("LC_",)


def browser_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the allowlisted part of ``os.environ``, plus *overrides*."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key in _PASS_THROUGH or key.startswith(_PASS_THROUGH_PREFIXES)
    }
    if overrides:
        env.update(overrides)
    return env

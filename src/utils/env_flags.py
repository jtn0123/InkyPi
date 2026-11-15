"""Read on/off environment variables the same way everywhere.

Each module used to keep its own truthy set, and they disagreed: ``on``
switched ``INKYPI_HTTP_LOG_LATENCY`` on but left ``INKYPI_FORCE_HTTPS``
off.
"""

from __future__ import annotations

import os

#: Values that switch a flag on, compared after stripping and lowercasing.
TRUTHY = frozenset({"1", "true", "yes", "on"})


def env_bool(name: str, default: bool = False) -> bool:
    """Return whether the environment variable *name* is switched on.

    An unset variable gives *default*. A set one is on only when it holds
    one of :data:`TRUTHY`, so ``INKYPI_X=`` switches a default-on flag off.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY

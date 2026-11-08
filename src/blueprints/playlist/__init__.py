"""The ``playlist`` blueprint: playlist pages, CRUD, rotation and ETA routes.

The blueprint object lives in :mod:`._common`; each sibling module registers
its routes on it at import time:

* :mod:`._add_plugin` — ``/add_plugin`` and its form parsing / validation.
* :mod:`._pages` — ``/playlist`` page, ``/playlists`` redirect and the
  ``format_relative_time`` template filter.
* :mod:`._crud` — create / update / delete playlist, ``/update_device_cycle``
  and ``/reorder_plugins``.
* :mod:`._display` — ``/display_next_in_playlist`` and the minute-cached
  ``/playlist/eta/<name>``.

:mod:`._schedule` holds the pure overlap and rotation-ETA math the routes
share.

Route-module helpers are intentionally not re-exported here: patch them where
they are looked up (e.g. ``blueprints.playlist._display.now_device_tz``).
"""

from . import _add_plugin, _crud, _display, _pages
from ._common import playlist_bp

#: Importing these modules registers their routes on ``playlist_bp``.
_ROUTE_MODULES = (_add_plugin, _pages, _crud, _display)

__all__ = ["playlist_bp"]

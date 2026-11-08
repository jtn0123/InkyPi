"""The ``plugin`` blueprint: plugin pages, settings, instances and renders.

The blueprint object lives in :mod:`._common`; each sibling module registers
its routes on it at import time:

* :mod:`._pages` — ``/plugin/<id>`` settings page, ``/plugins`` index and the
  AI Image prompt helper the settings page calls.
* :mod:`._images` — plugin static assets, latest-history and instance previews.
* :mod:`._instances` — delete / update / display / force-retry an instance.
* :mod:`._update_now` — ``/update_now`` (sync + async) and ``/api/job/<id>``.
* :mod:`._settings_save` — ``/save_plugin_settings`` and its alias route.

Route-module helpers are intentionally not re-exported here: patch them where
they are looked up (e.g. ``blueprints.plugin._update_now.get_plugin_instance``).
"""

from . import _images, _instances, _pages, _settings_save, _update_now
from ._common import plugin_bp

#: Importing these modules registers their routes on ``plugin_bp``.
_ROUTE_MODULES = (_pages, _images, _instances, _update_now, _settings_save)

__all__ = ["plugin_bp"]

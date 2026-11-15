# pyright: reportMissingImports=false
"""Rendered plugin pages must not repeat an ``id`` attribute (JTN-314).

A duplicated id breaks ``getElementById``, ``<label for>`` and
``aria-describedby``: each points at only the first element with that id.
The 2026-04-06 dogfood audit found 136 duplicates from injected markup.
"""

import re

from flask.testing import FlaskClient

# Plugin ids that can be rendered without external API credentials
_RENDERABLE_PLUGINS = [
    "clock",
    "calendar",
    "weather",
    "ai_image",
    "rss",
    "countdown",
    "year_progress",
]


def _find_duplicate_ids(html: str) -> list[str]:
    """Return a list of id values that appear more than once in the HTML."""
    ids = re.findall(r'\bid="([^"]+)"', html)
    seen: dict[str, int] = {}
    for id_val in ids:
        seen[id_val] = seen.get(id_val, 0) + 1
    return [id_val for id_val, count in seen.items() if count > 1]


def test_plugin_pages_have_no_duplicate_ids(client: FlaskClient) -> None:
    """Rendered plugin pages must not contain any duplicate id attributes."""
    for plugin_id in _RENDERABLE_PLUGINS:
        resp = client.get(f"/plugin/{plugin_id}")
        if resp.status_code != 200:
            continue
        html = resp.get_data(as_text=True)
        dupes = _find_duplicate_ids(html)
        assert (
            dupes == []
        ), f"/plugin/{plugin_id} has duplicate id attribute(s): {dupes}"

"""Display-name helpers for plugin instances.

Plugin instances carry an internal ``name`` attribute that doubles as the
filesystem settings key (e.g. ``weather_saved_settings``).  When the user
has never renamed the instance, this raw key should not leak into
user-facing surfaces like the dashboard "NOW SHOWING" panel, the playlists
list, or history entries.

The helpers in this module centralise the logic for deriving a friendly
label from the internal key, with a stable fallback order:

    1. A non-auto-generated user-supplied instance name, if any.
    2. The plugin's ``display_name`` (from ``plugin-info.json``).
    3. A humanised version of the ``plugin_id`` (e.g. ``image_folder`` ->
       ``Image Folder``).
    4. The raw instance name as a last resort.
"""

from __future__ import annotations

_AUTO_SUFFIX = "_saved_settings"


def is_auto_instance_name(instance_name: str | None, plugin_id: str | None) -> bool:
    """Return True when ``instance_name`` matches the auto-generated pattern.

    The auto-generated instance name is ``{plugin_id}_saved_settings`` — this
    is what the backend uses when a user saves settings from a plugin page
    without creating a named instance.  Such names should be suppressed in
    UI surfaces because they're internal filesystem keys, not user-chosen
    labels.
    """
    if not instance_name or not plugin_id:
        return False
    return instance_name == f"{plugin_id}{_AUTO_SUFFIX}"


def humanize_plugin_id(plugin_id: str | None) -> str:
    """Convert a plugin id like ``image_folder`` to a Title-Cased label."""
    if not plugin_id:
        return ""
    return plugin_id.replace("_", " ").replace("-", " ").strip().title()


def friendly_instance_label(
    instance_name: str | None,
    plugin_id: str | None,
    plugin_display_name: str | None = None,
) -> str:
    """Return a user-facing label for a plugin instance.

    Prefers (in order): a user-renamed instance, the plugin's display name,
    a humanised plugin id, then the raw instance name.  Always returns a
    non-empty string when any input is present; returns an empty string if
    all inputs are missing.
    """
    if instance_name and not is_auto_instance_name(instance_name, plugin_id):
        return instance_name
    if plugin_display_name:
        return plugin_display_name
    humanised = humanize_plugin_id(plugin_id)
    if humanised:
        return humanised
    return instance_name or ""


def instance_suffix_label(
    instance_name: str | None,
    plugin_id: str | None,
) -> str | None:
    """Return an instance label suitable for appending in parentheses.

    Returns ``None`` when the instance name is auto-generated or missing —
    signalling to callers that no parenthesised suffix should be rendered.
    Otherwise returns the user-supplied instance name verbatim.
    """
    if not instance_name:
        return None
    if is_auto_instance_name(instance_name, plugin_id):
        return None
    return instance_name

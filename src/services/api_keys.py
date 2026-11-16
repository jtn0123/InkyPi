"""The provider API keys plugins read from ``.env``: the one list of them.

The API Keys page (``/settings/api-keys``) and its save and delete routes, the
key-name buttons on the generic ``/api-keys`` editor, and keyed backups all
read :data:`API_KEY_PROVIDERS`, so a key added here appears everywhere at once.
``tests/unit/test_api_key_registry.py`` fails when a plugin reads a key that
is not listed here, or a listed key's plugins are wrong.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApiKeyProvider:
    """One key in ``.env`` and the plugins that read it."""

    key: str
    """The variable name in ``.env``."""
    label: str
    """The provider's name, shown on the key's card."""
    slug: str
    """Stem of the card's element ids (``<slug>-input``, ``<slug>-status``)."""
    placeholder: str
    plugins: tuple[str, ...]
    """Ids of the plugins that read the key."""
    more: bool = False
    """Listed under "More providers" rather than at the top of the page."""
    delete_label: str | None = None
    """Name used in the Delete button's label, when not ``label``."""


API_KEY_PROVIDERS: tuple[ApiKeyProvider, ...] = (
    ApiKeyProvider(
        key="OPEN_WEATHER_MAP_SECRET",
        label="OpenWeather",
        slug="openweather",
        placeholder="Enter OpenWeather API key",
        plugins=("weather",),
    ),
    ApiKeyProvider(
        key="OPEN_AI_SECRET",
        label="OpenAI",
        slug="openai",
        placeholder="Enter OpenAI API key",
        plugins=("ai_image", "ai_text"),
    ),
    ApiKeyProvider(
        key="NASA_SECRET",
        label="NASA",
        slug="nasa",
        placeholder="Enter NASA API key",
        plugins=("apod",),
        delete_label="NASA APOD",
    ),
    ApiKeyProvider(
        key="UNSPLASH_ACCESS_KEY",
        label="Unsplash",
        slug="unsplash",
        placeholder="Enter Unsplash access key",
        plugins=("unsplash",),
    ),
    ApiKeyProvider(
        key="GITHUB_SECRET",
        label="GitHub",
        slug="github",
        placeholder="Enter GitHub personal access token",
        plugins=("github",),
        more=True,
    ),
    ApiKeyProvider(
        key="GOOGLE_AI_SECRET",
        label="Google AI",
        slug="googleai",
        placeholder="Enter Google AI API key",
        plugins=("ai_image", "ai_text"),
        more=True,
    ),
    ApiKeyProvider(
        key="IMMICH_KEY",
        label="Immich",
        slug="immich",
        placeholder="Enter Immich API key",
        plugins=("image_album",),
        more=True,
    ),
)

API_KEY_NAMES: frozenset[str] = frozenset(p.key for p in API_KEY_PROVIDERS)


def plugin_names_by_key(
    installed_plugins: Iterable[Mapping[str, object]],
) -> dict[str, list[str]]:
    """The display names of the plugins that read each key.

    *installed_plugins* is ``Config.get_plugins()``; a plugin that is not
    installed is shown by its id.
    """
    names = {
        str(plugin.get("id")): str(plugin.get("display_name") or plugin.get("id"))
        for plugin in installed_plugins
    }
    return {
        provider.key: [names.get(pid, pid) for pid in provider.plugins]
        for provider in API_KEY_PROVIDERS
    }

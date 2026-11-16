"""The provider-key list in ``services/api_keys.py`` is the only one.

The API Keys page in the menu once listed six keys while backups carried
seven, so the Immich key a plugin needs could not be entered there. These
tests fail when a plugin reads a key the list lacks, when the list names the
wrong plugins, or when an editor, the save and delete routes or a backup stop
covering every listed key.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from services.api_keys import API_KEY_NAMES, API_KEY_PROVIDERS

SRC = Path(__file__).resolve().parents[2] / "src"
PLUGINS = SRC / "plugins"

# Keys the app itself reads from .env that are not a plugin's provider key.
_APP_KEYS = {"SECRET_KEY"}

# A key name given to load_env_key, or named as a plugin's expected key or a
# multi-provider plugin's env_var.
_KEY_READ = re.compile(
    r"""load_env_key\(\s*["']([A-Z][A-Z0-9_]*)["']"""
    r"""|["'](?:expected_key|env_var)["']\s*:\s*["']([A-Z][A-Z0-9_]*)["']"""
)


def _keys_read(paths: list[Path]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        for match in _KEY_READ.finditer(path.read_text(encoding="utf-8")):
            found.add(match.group(1) or match.group(2))
    return found


def _plugin_ids() -> list[str]:
    return sorted(p.parent.name for p in PLUGINS.glob("*/plugin-info.json"))


def test_keys_and_slugs_are_unique() -> None:
    keys = [p.key for p in API_KEY_PROVIDERS]
    slugs = [p.slug for p in API_KEY_PROVIDERS]
    assert len(set(keys)) == len(keys)
    assert len(set(slugs)) == len(slugs)
    assert set(keys) == API_KEY_NAMES


def test_every_key_the_app_reads_is_listed() -> None:
    read = _keys_read(sorted(SRC.rglob("*.py")))
    assert read - _APP_KEYS <= API_KEY_NAMES, (
        "Add these keys to API_KEY_PROVIDERS in src/services/api_keys.py: "
        f"{sorted(read - _APP_KEYS - API_KEY_NAMES)}"
    )


@pytest.mark.parametrize("plugin_id", _plugin_ids())
def test_each_plugin_is_listed_against_exactly_the_keys_it_reads(
    plugin_id: str,
) -> None:
    sources = sorted((PLUGINS / plugin_id).rglob("*.py"))
    read = {
        key
        for key in API_KEY_NAMES
        if any(f'"{key}"' in path.read_text(encoding="utf-8") for path in sources)
    }
    listed = {p.key for p in API_KEY_PROVIDERS if plugin_id in p.plugins}
    assert listed == read


def test_every_plugin_that_needs_a_key_has_one_listed() -> None:
    needs_key = {
        plugin_id
        for plugin_id in _plugin_ids()
        if json.loads((PLUGINS / plugin_id / "plugin-info.json").read_text()).get(
            "requires_api_key"
        )
    }
    listed = {pid for p in API_KEY_PROVIDERS for pid in p.plugins}
    assert needs_key == listed


def test_the_menu_page_has_a_card_for_every_key(client: FlaskClient) -> None:
    body = client.get("/settings/api-keys").get_data(as_text=True)

    assert f"{len(API_KEY_PROVIDERS)} providers" in body
    for provider in API_KEY_PROVIDERS:
        assert f'id="{provider.slug}-input" name="{provider.key}"' in body
        assert f'id="{provider.slug}-status"' in body


def test_the_menu_page_names_the_plugins_that_use_a_key(
    client: FlaskClient,
) -> None:
    body = client.get("/settings/api-keys").get_data(as_text=True)

    assert "Used by Image Album" in body


def test_the_generic_editor_offers_every_key(client: FlaskClient) -> None:
    body = client.get("/api-keys").get_data(as_text=True)

    for provider in API_KEY_PROVIDERS:
        assert f'data-key="{provider.key}"' in body


@pytest.mark.parametrize("key", sorted(API_KEY_NAMES))
def test_every_key_can_be_saved_and_deleted_from_the_menu_page(
    client: FlaskClient, device_config_dev: Any, key: str
) -> None:
    saved = client.post("/settings/save_api_keys", data={key: "value-1234"})

    assert saved.status_code == 200
    assert saved.get_json()["updated"] == [key]
    assert device_config_dev.load_env_key(key) == "value-1234"

    deleted = client.post("/settings/delete_api_key", data={"key": key})

    assert deleted.status_code == 200
    assert device_config_dev.load_env_key(key) is None


def test_a_backup_carries_every_listed_key() -> None:
    from blueprints.settings import _config

    assert _config._BACKUP_ENV_KEYS == API_KEY_NAMES


def test_a_key_saved_before_the_list_existed_still_shows_as_configured(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """Keys already in .env keep working: the names did not change."""
    device_config_dev.set_env_key("IMMICH_KEY", "immich-abcd")

    body = client.get("/settings/api-keys").get_data(as_text=True)

    assert "...abcd (11 chars)" in body

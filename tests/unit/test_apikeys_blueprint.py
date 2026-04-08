# pyright: reportMissingImports=false
"""Tests for blueprints/apikeys.py."""

import os
from pathlib import Path
from unittest.mock import patch

# ---- Helper functions ----


def test_parse_env_file_nonexistent(tmp_path):
    from blueprints.apikeys import parse_env_file

    result = parse_env_file(str(tmp_path / "nonexistent.env"))
    assert result == []


def test_parse_env_file_valid(tmp_path):
    from blueprints.apikeys import parse_env_file

    env_file = tmp_path / ".env"
    env_file.write_text("KEY1=value1\nKEY2=value2\n")
    result = parse_env_file(str(env_file))
    assert ("KEY1", "value1") in result
    assert ("KEY2", "value2") in result


def test_parse_env_file_error(tmp_path):
    from blueprints.apikeys import parse_env_file

    with patch(
        "blueprints.apikeys.dotenv_values", side_effect=Exception("parse error")
    ):
        result = parse_env_file(str(tmp_path / ".env"))
    assert result == []


def test_write_env_file_basic(tmp_path):
    from blueprints.apikeys import write_env_file

    env_path = str(tmp_path / ".env")
    result = write_env_file(env_path, [("API_KEY", "abc123"), ("SECRET", "xyz")])
    assert result is True
    content = Path(env_path).read_text()
    assert "API_KEY=abc123" in content
    assert "SECRET=xyz" in content


def test_write_env_file_quoted_values(tmp_path):
    from blueprints.apikeys import write_env_file

    env_path = str(tmp_path / ".env")
    result = write_env_file(env_path, [("KEY", "has spaces")])
    assert result is True
    content = Path(env_path).read_text()
    assert 'KEY="has spaces"' in content


def test_write_env_file_value_with_double_quote(tmp_path):
    """Bug 7: Values with double-quotes should be escaped, not corrupt the file."""
    from blueprints.apikeys import parse_env_file, write_env_file

    env_path = str(tmp_path / ".env")
    result = write_env_file(env_path, [("KEY", 'value"with"quotes')])
    assert result is True
    content = Path(env_path).read_text()
    # The value should be quoted and internal quotes escaped
    assert '\\"' in content
    # Verify it round-trips correctly
    entries = parse_env_file(env_path)
    vals = dict(entries)
    assert vals.get("KEY") == 'value"with"quotes'


def test_write_env_file_control_chars(tmp_path):
    from blueprints.apikeys import write_env_file

    env_path = str(tmp_path / ".env")
    result = write_env_file(env_path, [("KEY", "bad\nvalue")])
    assert result is False


def test_write_env_file_error(tmp_path):
    from blueprints.apikeys import write_env_file

    result = write_env_file("/nonexistent/dir/.env", [("KEY", "val")])
    assert result is False


def test_mask_value_normal():
    from blueprints.apikeys import mask_value

    result = mask_value("my_secret_key")
    assert "●" in result
    assert len(result) <= 20


def test_mask_value_empty():
    from blueprints.apikeys import mask_value

    assert mask_value("") == "(empty)"
    assert mask_value(None) == "(empty)"


def test_get_env_path_with_project_dir(monkeypatch):
    from blueprints.apikeys import get_env_path

    monkeypatch.setenv("PROJECT_DIR", "/custom/project")
    assert get_env_path() == "/custom/project/.env"


def test_get_env_path_default(monkeypatch):
    from blueprints.apikeys import get_env_path

    monkeypatch.delenv("PROJECT_DIR", raising=False)
    result = get_env_path()
    assert result.endswith(".env")


# ---- Route tests ----


def test_apikeys_page_renders(client, tmp_path, monkeypatch):
    env_path = str(tmp_path / ".env")
    Path(env_path).write_text("TEST_KEY=hidden\n")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: env_path)

    resp = client.get("/api-keys")
    assert resp.status_code == 200


def test_save_apikeys_success(client, tmp_path, monkeypatch):
    env_path = str(tmp_path / ".env")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: env_path)

    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": "MY_KEY", "value": "my_value"}]},
    )
    assert resp.status_code == 200
    assert os.path.exists(env_path)


def test_save_apikeys_invalid_json(client):
    resp = client.post(
        "/api-keys/save", data="not json", content_type="application/json"
    )
    assert resp.status_code == 400


def test_save_apikeys_invalid_entries(client):
    resp = client.post("/api-keys/save", json={"entries": "not-a-list"})
    assert resp.status_code == 400


def test_save_apikeys_invalid_key_format(client, tmp_path, monkeypatch):
    env_path = str(tmp_path / ".env")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: env_path)

    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": "BAD KEY!", "value": "val"}]},
    )
    assert resp.status_code == 400


def test_save_apikeys_keep_existing(client, tmp_path, monkeypatch):
    env_path = str(tmp_path / ".env")
    Path(env_path).write_text("EXISTING=secret_val\n")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: env_path)

    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": "EXISTING", "keepExisting": True}]},
    )
    assert resp.status_code == 200
    content = Path(env_path).read_text()
    assert "secret_val" in content


def test_save_apikeys_control_chars(client, tmp_path, monkeypatch):
    env_path = str(tmp_path / ".env")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: env_path)

    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": "KEY", "value": "bad\nvalue"}]},
    )
    assert resp.status_code == 400


def test_save_apikeys_updates_existing_key_when_new_value_provided(
    client, tmp_path, monkeypatch
):
    """JTN-250: Sending a new value for an existing key must update it, not discard it."""
    env_path = str(tmp_path / ".env")
    Path(env_path).write_text("MY_SECRET=old_value\n")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: env_path)

    # Simulate what the fixed JS sends: { key, value } (no keepExisting) for an
    # existing row where the user typed a new value.
    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": "MY_SECRET", "value": "new_value"}]},
    )
    assert resp.status_code == 200
    content = Path(env_path).read_text()
    assert "new_value" in content
    assert "old_value" not in content


def test_save_apikeys_preserves_existing_key_when_no_new_value(
    client, tmp_path, monkeypatch
):
    """JTN-250: Sending keepExisting=True for an existing key must preserve the stored value."""
    env_path = str(tmp_path / ".env")
    Path(env_path).write_text("MY_SECRET=original_value\n")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: env_path)

    # Simulate what the fixed JS sends: { key, value: null, keepExisting: true }
    # when the user left the field blank.
    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": "MY_SECRET", "value": None, "keepExisting": True}]},
    )
    assert resp.status_code == 200
    content = Path(env_path).read_text()
    assert "original_value" in content

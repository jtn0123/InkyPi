# pyright: reportMissingImports=false, reportMissingModuleSource=false
import importlib.util
import os
from pathlib import Path

import pytest

# Dynamically import src/config.py as module name 'config' for tests and linters
_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
_CONFIG_PATH = _SRC_DIR / "config.py"
_spec = importlib.util.spec_from_file_location("config", str(_CONFIG_PATH))
assert _spec and _spec.loader, "Failed to locate config module"
config_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config_mod)


def test_get_env_file_path_uses_PROJECT_DIR(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    cfg = config_mod.Config()
    env_path = cfg.get_env_file_path()
    assert env_path == os.path.join(str(tmp_path), ".env")


def test_get_env_file_path_defaults_to_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROJECT_DIR", raising=False)
    cfg = config_mod.Config()
    expected = os.path.abspath(os.path.join(cfg.BASE_DIR, "..", ".env"))
    env_path = cfg.get_env_file_path()
    assert env_path == expected


def test_set_and_load_env_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("NASA_SECRET", raising=False)

    cfg = config_mod.Config()

    # Set a key
    assert cfg.set_env_key("NASA_SECRET", "abc123") is True

    # Load the key using the same API as plugins
    value = cfg.load_env_key("NASA_SECRET")
    assert value == "abc123"

    # Ensure file was written
    env_file = cfg.get_env_file_path()
    assert os.path.exists(env_file)
    with open(env_file) as f:
        content = f.read()
    # dotenv may write quoted or unquoted values; validate key presence and value occurrence
    assert "NASA_SECRET=" in content
    assert "abc123" in content


def test_unset_env_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("NASA_SECRET", raising=False)

    cfg = config_mod.Config()
    cfg.set_env_key("NASA_SECRET", "to_remove")

    assert cfg.unset_env_key("NASA_SECRET") is True

    # Should not be present in process env
    assert os.getenv("NASA_SECRET") is None

    # And should not be present when loading from file
    value = cfg.load_env_key("NASA_SECRET")
    assert value is None


def test_load_env_key_reads_one_value_and_leaves_the_environment_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .env entry like OPENAI_BASE_URL must not reconfigure the OpenAI client."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    for name in ("OPEN_AI_SECRET", "OPENAI_BASE_URL", "HTTPS_PROXY"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "OPEN_AI_SECRET=sk-1\n"
        "OPENAI_BASE_URL=https://attacker.example\n"
        "HTTPS_PROXY=http://attacker.example:8080\n"
    )

    cfg = config_mod.Config()

    assert cfg.load_env_key("OPEN_AI_SECRET") == "sk-1"
    assert "OPENAI_BASE_URL" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert "OPEN_AI_SECRET" not in os.environ


def test_a_key_removed_from_the_file_stops_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API Keys page rewrites .env; a deleted key must not linger."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("NASA_SECRET", raising=False)
    cfg = config_mod.Config()
    cfg.set_env_key("NASA_SECRET", "old")
    assert cfg.load_env_key("NASA_SECRET") == "old"

    (tmp_path / ".env").write_text("SECRET_KEY=x\n")

    assert cfg.load_env_key("NASA_SECRET") is None


def test_load_env_key_prefers_the_file_then_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("NASA_SECRET", "from-shell")
    monkeypatch.setenv("GITHUB_SECRET", "from-shell")
    (tmp_path / ".env").write_text("NASA_SECRET=from-file\n")

    cfg = config_mod.Config()

    assert cfg.load_env_key("NASA_SECRET") == "from-file"
    assert cfg.load_env_key("GITHUB_SECRET") == "from-shell"

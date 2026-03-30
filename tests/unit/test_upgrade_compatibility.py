import shutil
import sqlite3
from pathlib import Path


def test_config_loads_legacy_fixture(monkeypatch, tmp_path):
    import config as config_mod

    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "upgrade" / "device_v1.json"
    )
    config_path = tmp_path / "device.json"
    shutil.copyfile(fixture, config_path)

    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))

    cfg = config_mod.Config()
    assert cfg.get_config("name") == "InkyPi Legacy"
    assert cfg.get_playlist_manager().playlists


def test_invalid_legacy_refresh_info_falls_back(monkeypatch, tmp_path):
    import config as config_mod

    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "upgrade"
        / "device_v1_invalid_refresh.json"
    )
    config_path = tmp_path / "device.json"
    shutil.copyfile(fixture, config_path)

    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))

    cfg = config_mod.Config()
    refresh_info = cfg.get_refresh_info()
    assert refresh_info.refresh_type == "Manual Update"
    assert refresh_info.plugin_id == ""


def test_benchmark_schema_upgrades_legacy_columns(tmp_path):
    from benchmarks.benchmark_storage import _ensure_schema

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE refresh_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refresh_id TEXT NOT NULL,
            ts REAL NOT NULL,
            plugin_id TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE stage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refresh_id TEXT NOT NULL,
            ts REAL NOT NULL,
            stage TEXT NOT NULL
        )
        """
    )
    _ensure_schema(conn)
    refresh_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(refresh_events)").fetchall()
    }
    stage_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(stage_events)").fetchall()
    }
    conn.close()

    assert "preprocess_ms" in refresh_columns
    assert "display_ms" in refresh_columns
    assert "memory_percent" in refresh_columns
    assert "extra_json" in stage_columns


def test_benchmarks_api_handles_legacy_schema(client, device_config_dev, tmp_path):
    db_path = tmp_path / "legacy_api.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE refresh_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refresh_id TEXT NOT NULL,
            ts REAL NOT NULL,
            plugin_id TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO refresh_events (refresh_id, ts, plugin_id) VALUES (?, ?, ?)",
        ("legacy-1", 1_700_000_000.0, "clock"),
    )
    conn.commit()
    conn.close()

    device_config_dev.update_value("benchmarks_db_path", str(db_path), write=True)

    summary = client.get("/api/benchmarks/summary?window=24h")
    refreshes = client.get("/api/benchmarks/refreshes?limit=5")
    plugins = client.get("/api/benchmarks/plugins?window=24h")

    assert summary.status_code == 200
    assert refreshes.status_code == 200
    assert plugins.status_code == 200
    assert summary.get_json()["success"] is True
    assert refreshes.get_json()["success"] is True
    assert plugins.get_json()["success"] is True

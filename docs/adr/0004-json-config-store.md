# ADR-0004: JSON file as the sole config and state store

**Status:** Accepted

## Context

InkyPi needs to persist device settings, playlist definitions, plugin instance configurations, and the last-refresh metadata across restarts. The deployment target is a single Raspberry Pi Zero 2 W running a systemd service. There is no multi-user, multi-process write contention beyond the one Flask worker and one background refresh thread. Simplicity of installation and inspectability of stored data are high priorities.

## Decision

All persistent state lives in a single `device.json` file (or `device_dev.json` in dev mode). The `Config` class in `src/config.py` is the sole reader and writer. Writes use a write-then-atomic-rename pattern (`Config.write_config()`) to prevent partial writes corrupting the file. Concurrent read/write access within the process is serialised by a `threading.RLock` (`_config_lock`). Schema validation runs on startup via `src/utils/config_schema.py` (added in commit `86f9cfc`, JTN-335). An mtime-based read cache was added in commit `cdbbc81` (JTN-519) to avoid re-parsing JSON on every route handler invocation.

## Consequences

### Positive
- Zero runtime database dependency — no SQLite, PostgreSQL, or Redis needed on the Pi.
- The file is human-readable and editable with any text editor; easy to inspect, back up, and restore (`src/config` CLI — JTN-336).
- Installation is a single `pip install` + file copy; no `CREATE TABLE` migrations.
- Plugin instance export/import (JTN-448) is trivially serialisable as JSON.

### Negative
- Not suitable for high write frequency; heavy playlist cycling writes the whole file on every tick. In practice, writes are infrequent (once per refresh, default 1 h).
- A process crash mid-write could corrupt the file; the atomic-rename mitigates this but does not eliminate all edge cases on FAT32/SD cards.
- As the number of plugins and history entries grows, the file grows with them; no built-in compaction.
- Multi-instance deployments (e.g., two Pis sharing a config) are not supported — each device owns its own file.

## Alternatives considered

- **SQLite** — richer query support and transaction safety, but adds a native-library dependency and requires schema migrations. The Pi Zero 2 W's SD card I/O characteristics also make SQLite's WAL mode less attractive.
- **Redis / key-value store** — overkill for a device that runs one Flask process; adds a daemon to manage.
- **Environment variables only** — suitable for secrets (handled via `.env` + `python-dotenv`) but not for structured nested config.

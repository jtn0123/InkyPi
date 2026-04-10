# Architecture Decision Records

This directory captures significant architectural decisions made in the InkyPi project. Each record (ADR) explains the context that drove a decision, what was decided, its trade-offs, and the alternatives that were considered but rejected.

Template: [0000-template.md](0000-template.md)

When to file a new ADR: when you make a choice that is non-obvious, hard to reverse, or likely to be re-litigated by a future contributor. Good candidates are library choices, concurrency models, persistence strategies, and protocol decisions.

---

| # | Title | Status | Summary |
|---|-------|--------|---------|
| [0001](0001-subprocess-plugin-isolation.md) | Subprocess isolation for plugin execution | Accepted | Each plugin runs in a child process so a crash or memory leak cannot bring down the web server. |
| [0002](0002-http-cache-strategy.md) | Custom in-process HTTP cache with TTL | Accepted | A bespoke TTL+LRU cache in `http_utils.py` reduces external API calls without adding a SQLite or Redis dependency. |
| [0003](0003-playlist-scheduling.md) | Playlist scheduling — time windows, priority, and cycle interval | Accepted | Three orthogonal axes (time window, priority, cycle interval) cover the common multi-playlist use case with pure in-memory evaluation. |
| [0004](0004-json-config-store.md) | JSON file as the sole config and state store | Accepted | A single `device.json` file keeps the deployment dependency-free and human-readable on a Pi. |
| [0005](0005-waitress-vs-gunicorn.md) | Waitress as the production WSGI server | Accepted | Waitress is single-process/multi-thread, avoiding fork-after-thread hazards that would break the in-process refresh task. |
| [0006](0006-webp-on-the-fly-encoding.md) | WebP encoding on request rather than at generation time | Accepted | Images are encoded to WebP at serve time with an LRU cache; PNGs remain the on-disk canonical format for drivers and exports. |

# ADR-0003: Playlist scheduling — time windows, priority, and cycle interval

**Status:** Accepted

## Context

Users want different content at different times of day: a clock overnight, news in the morning, weather in the afternoon. They also want to cycle through multiple plugins within a time window at a configurable rate. The scheduling model must be simple enough for a non-technical user to configure via the web UI, and it must work without a persistent scheduler process or database.

## Decision

Scheduling is encoded in three orthogonal axes, all stored in `device.json` and evaluated on every refresh tick:

1. **Time window** (`start_time` / `end_time` on `Playlist`): a playlist is only eligible when the current wall-clock time falls inside `[start_time, end_time)`. Times are `HH:MM` strings; `24:00` is the canonical end-of-day sentinel. Evaluated by `Playlist.is_active()` in `src/model.py` (line 282).

2. **Priority** (`Playlist.get_priority()`): when multiple playlists are active at the same time (overlapping windows), the one with the numerically lowest priority value wins. `PlaylistManager.determine_active_playlist()` sorts active playlists by priority and picks `[0]` (model.py line 173).

3. **Cycle interval** (`plugin_cycle_interval_seconds` on the device config, defaulting to 3600 s): the refresh task's `_wait_for_trigger()` sleeps for this duration between ticks. Per-plugin `refresh_interval` (stored on `PluginInstance`) allows individual plugins to declare a minimum cadence independently of the playlist cycle; `PlaylistManager.should_refresh()` checks elapsed time against the interval (model.py line 233).

Within an active playlist, plugins cycle round-robin via `Playlist.get_next_eligible_plugin()`, skipping plugins that fail `is_show_eligible()` (e.g., circuit-broken plugins).

## Consequences

### Positive
- No external cron or scheduler needed — evaluation is pure in-memory arithmetic on every tick.
- Priority + time windows covers the common "morning briefing / overnight clock" pattern with no special-case logic.
- Round-robin within a playlist gives equal share of screen time without requiring the user to set explicit durations.

### Negative
- Overlapping time windows with equal priority are non-deterministic (sort is not stable across restarts) — users must assign distinct priorities if they want predictable overlap resolution.
- The cycle interval is global; giving one playlist a faster cadence than another requires separate priority + time window configuration rather than a per-playlist interval setting.
- Midnight-spanning windows (`start > end`, e.g., 22:00–06:00) are supported by `is_active()` but not surfaced clearly in the UI, which can confuse users.

## Alternatives considered

- **cron expressions per plugin** — more flexible, but far harder to expose in a web UI aimed at non-technical users; also requires a persistent scheduler.
- **Fixed time slots per plugin** — simpler for users to reason about, but inflexible and requires the user to account for plugin run time.
- **Event-driven (sunrise/sunset)** — requested as a future feature; not implemented because it requires a location-aware time source and adds complexity outside the initial scope.

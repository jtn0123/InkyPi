# ADR-0001: Subprocess isolation for plugin execution

**Status:** Accepted

## Context

InkyPi plugins are third-party or user-written code that fetch external data and render images. A buggy plugin can leak memory, spin indefinitely, open file handles, or crash the interpreter. The refresh loop runs inside the same process as the Flask web server, so an uncaught exception or OOM kill in a plugin would bring down the web UI too. On a Pi Zero 2 W (512 MB RAM, no swap by default), unbounded memory growth from a single plugin is a real operational concern.

## Decision

Each plugin invocation is run in a separate child process via Python's `multiprocessing` module (see `src/refresh_task/worker.py`). On Linux (the production target) the `forkserver` start method is preferred because it spawns children from a lean server process rather than duplicating the parent's full heap on every `fork()`. The child writes the image to a PNG tempfile and puts the file path (plus optional metadata and any plugin-state changes) onto a `multiprocessing.Queue` and exits; the parent reads the queue, loads the image, and re-raises any exception as a structured error. Sending the path rather than the bytes keeps the payload below the pipe buffer, which a full PNG would block on (see `_execute_refresh_attempt_worker`). The `_get_mp_context()` helper in `worker.py` encapsulates the platform-specific method selection.

## Consequences

### Positive
- A crashing or OOM-killed plugin cannot take down the web UI.
- Memory leaks are bounded to a single refresh cycle — the child process is reclaimed by the OS on exit.
- The circuit breaker (`_update_plugin_health` in `src/refresh_task/health_hooks.py`, backed by `PluginHealthTracker` in `health.py`) can track consecutive failures and pause a plugin without affecting others.

### Negative
- Subprocess spawn is slower than a direct function call; on a Pi Zero 2 W `forkserver` adds ~200-400 ms of overhead per refresh.
- Plugin objects must be picklable (or reconstructed from config) to cross the process boundary — `Config` implements `__getstate__`/`__setstate__` for this reason (`src/config.py`), and the worker rebuilds its `Config` from a picklable `RefreshContext` (`src/refresh_task/context.py`).
- Debugging is harder because tracebacks must be serialised as strings and re-raised in the parent.

## Alternatives considered

- **Run plugins in threads** — simpler and faster, but a crashing plugin or GIL-bypassing C extension can corrupt shared state, and memory leaks accumulate in the main process indefinitely.
- **Run plugins in the same thread** — fastest, but any unhandled exception kills the refresh loop.
- **Docker/sandbox per plugin** — complete isolation, but far too heavyweight for a Pi Zero 2 W.

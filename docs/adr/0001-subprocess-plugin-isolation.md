# ADR-0001: Subprocess isolation for plugin execution

**Status:** Accepted

## Context

InkyPi plugins are third-party or user-written code that fetch external data and render images. A buggy plugin can leak memory, spin indefinitely, open file handles, or crash the interpreter. The refresh loop runs inside the same process as the Flask web server, so an uncaught exception or OOM kill in a plugin would bring down the web UI too. On a Pi Zero 2 W (512 MB RAM, no swap by default), unbounded memory growth from a single plugin is a real operational concern.

## Decision

Each plugin invocation is run in a separate child process via Python's `multiprocessing` module (see `src/refresh_task/worker.py`). On Linux (the production target) the `forkserver` start method is preferred because it spawns children from a lean server process rather than duplicating the parent's full heap on every `fork()`. The child serialises its result (PNG bytes + optional metadata) onto a `multiprocessing.Queue` and exits; the parent reads the queue and re-raises any exception as a structured error. The `_get_mp_context()` helper in `worker.py` encapsulates the platform-specific method selection (line 14-24).

## Consequences

### Positive
- A crashing or OOM-killed plugin cannot take down the web UI.
- Memory leaks are bounded to a single refresh cycle — the child process is reclaimed by the OS on exit.
- The circuit breaker in `_update_plugin_health` (task.py) can track consecutive failures and pause a plugin without affecting others.

### Negative
- Subprocess spawn is slower than a direct function call; on a Pi Zero 2 W `forkserver` adds ~200-400 ms of overhead per refresh.
- Plugin objects must be picklable (or reconstructed from config) to cross the process boundary — `Config` implements `__getstate__`/`__setstate__` for this reason (`src/config.py` lines 90-104).
- Debugging is harder because tracebacks must be serialised as strings and re-raised in the parent.

## Alternatives considered

- **Run plugins in threads** — simpler and faster, but a crashing plugin or GIL-bypassing C extension can corrupt shared state, and memory leaks accumulate in the main process indefinitely.
- **Run plugins in the same thread** — fastest, but any unhandled exception kills the refresh loop.
- **Docker/sandbox per plugin** — complete isolation, but far too heavyweight for a Pi Zero 2 W.

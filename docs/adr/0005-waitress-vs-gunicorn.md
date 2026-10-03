# ADR-0005: Waitress as the production WSGI server

**Status:** Accepted

## Context

InkyPi needs a production-grade WSGI server to replace Flask's built-in development server. The two most common choices in the Python ecosystem are Waitress and Gunicorn. The application runs a background `RefreshTask` thread that was started in the same process as the Flask app (`src/inkypi.py` line 370). Gunicorn's pre-fork worker model would fork the process after the refresh thread is already running, which is undefined behaviour in Python — threads do not survive `fork()` safely, and the forked workers would each hold a copy of the thread object pointing at state owned by the parent.

## Decision

Waitress (`waitress==3.0.2`, listed in `install/requirements.txt`) is used as the WSGI server. The entry point in `src/inkypi.py` calls `waitress.serve(created_app, host="0.0.0.0", port=PORT, threads=4)`. The thread count was raised from 1 to 4 in commit `90c44c2` (fix #142) after profiling showed single-threaded Waitress blocking on concurrent requests during manual plugin refreshes. The thread count is read from `INKYPI_WEB_THREADS` (default 4; it was briefly lowered to 2, which let two open SSE streams starve every other request).

Waitress is a pure-Python, multi-threaded server that runs in the same process as the application. There is no forking — the refresh thread, config lock, and event bus are all shared safely with the WSGI threads via the existing `threading.RLock`.

## Consequences

### Positive
- No `fork()`-after-thread hazard; the refresh task and Flask workers share a single process with proper locking.
- Pure-Python install — no C extensions, no `libpython` headers required on the Pi.
- Works on Windows (useful for contributors developing on Windows without WSL).
- Thread count is a simple integer tunable via code or env; no worker process management.

### Negative
- Waitress is multi-threaded but single-process; it cannot use multiple CPU cores the way Gunicorn with multiple worker processes can. On a Pi Zero 2 W (single-core effective throughput) this is not a concern.
- Waitress does not support HTTP/2 or WebSockets natively; SSE (`/api/events`, `/api/progress/stream`) is handled by Flask's streaming response, which pins one worker thread per open stream. `src/utils/sse.py` therefore caps concurrent streams at `threads - 2` (the newest stream evicts the oldest; 503 + `Retry-After` while an eviction is still winding down), ends each response after ~55 s so EventSource reconnects and threads are recycled, and polls for client disconnects (`channel_request_lookahead=1` makes `waitress.client_disconnected` accurate) so closed tabs free their thread within ~1 s.
- Slightly less battle-tested at high concurrency compared to Gunicorn + gevent; acceptable for a single-Pi deployment with at most a handful of simultaneous browser tabs.

## Alternatives considered

- **Gunicorn with sync workers** — incompatible with the in-process refresh thread; forking after thread start is unsafe.
- **Gunicorn with `--preload` disabled and gevent workers** — would require converting the entire codebase to async-compatible patterns.
- **uWSGI** — C extension, heavier deployment footprint, thread model has the same forking caveats as Gunicorn.
- **Flask dev server** — used in `--dev` mode only; explicitly not suitable for production.

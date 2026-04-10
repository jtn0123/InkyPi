# ADR-0002: Custom in-process HTTP cache with TTL

**Status:** Accepted

## Context

Plugins call external APIs (weather, news, NASA APOD, Unsplash, etc.) on every refresh cycle. With a 5-minute refresh interval a single plugin can make ~288 API calls per day — often far beyond free-tier quotas. On a Pi Zero 2 W, each outbound HTTPS request also adds meaningful latency and power draw. An off-the-shelf solution such as `requests-cache` would work, but it introduces a SQLite or filesystem dependency and requires per-plugin opt-in. The project already avoids SQLite as a runtime dependency (see ADR-0004); adding it only for response caching seemed disproportionate.

## Decision

A custom `HTTPCache` class lives in `src/utils/http_cache.py`. It is an `OrderedDict`-backed, thread-safe, TTL+LRU store keyed on the full request URL (including query string). The helper `http_get()` in `src/utils/http_utils.py` wraps `requests.get()` and is the single call site all plugins use. Cache entries honour the server's `Cache-Control: max-age` when present; the default TTL is 300 s (overridable via `INKYPI_HTTP_CACHE_TTL_S`). LRU eviction was added in commit `6bc5ce7` (JTN-299) after the initial implementation allowed unbounded growth.

## Consequences

### Positive
- No new runtime dependencies — pure Python, no SQLite.
- Plugins benefit automatically without any code changes; `http_get()` is already the conventional call.
- Cache is scoped to the process lifetime; no stale entries survive a service restart.
- Statistics (`hits`, `misses`, `hit_rate`) are exposed for monitoring.

### Negative
- Cache is lost on restart — a cold start always fetches live data.
- The cache is in-process only; if InkyPi is run as multiple workers behind a load balancer (not the current deployment model), each worker has its own cache.
- Cache-key logic is URL-only; `POST` bodies or custom headers are not keyed, but plugins only use `GET`.

## Alternatives considered

- **`requests-cache`** — mature library, but brings a SQLite/filesystem backend that conflicts with the project's no-database stance and requires explicit integration per plugin.
- **No cache / rely on ETags** — not all external APIs send `ETag`; even conditional requests consume quota on many services.
- **Redis** — overkill for a single-Pi deployment.

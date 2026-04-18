# HTTP Performance Guide for Plugin Authors

InkyPi targets the Raspberry Pi Zero 2 W (512 MB RAM, single-core-class throughput). Every
unnecessary TLS handshake adds 100–400 ms of CPU and wall-clock time. This guide explains
the HTTP infrastructure available to plugins and how to use it correctly.

## Why use `get_http_session()`

`get_http_session()` (`src/utils/http_client.py`, line 32) returns the plugin-facing
compatibility session. Its pool/adapter wiring is built from the same shared helper used
by `http_get()` in `src/utils/http_utils.py`, so the retry, pooling, and header defaults
are easier to reason about across both entry points. Using a shared session has three
concrete benefits on Pi hardware:

1. **TLS session resumption** – once a TLS handshake has been negotiated with a host, the
   underlying SSL session can be reused across requests. A cold TLS handshake to a CDN or
   weather API costs ~200–400 ms on Pi Zero. Reuse costs near zero.
2. **TCP keep-alive / connection reuse** – HTTP/1.1 keep-alive keeps the TCP socket open
   between requests to the same host. On Pi Zero, even a TCP three-way handshake is
   measurable (~20–50 ms to a nearby host, more to a distant one).
3. **Automatic retry on transient failures** – the adapter attached to the session
   (lines 53–66 of `src/utils/http_client.py`) retries on HTTP 429, 500, 502, 503, 504
   with a 0.5 s exponential backoff, up to 3 total attempts, for idempotent methods
   (GET, HEAD, OPTIONS).

Calling `requests.get(url)` directly creates a new one-shot session for every request,
paying the full TLS + TCP cost every time and getting no retry behaviour.

## Pool size rationale

The shared adapter is configured with (lines 59–64 of `src/utils/http_client.py`):

```python
requests.adapters.HTTPAdapter(
    pool_connections=10,   # number of distinct host connection pools
    pool_maxsize=10,       # sockets kept open per host pool
    max_retries=retry_strategy,
    pool_block=False,
)
```

**Why 10?** InkyPi typically runs one refresh cycle at a time and talks to a handful of
external hosts (weather API, GitHub, Wikimedia, etc.). Ten pools cover the realistic
maximum of distinct hosts in a refresh cycle without holding open dozens of sockets that a
512 MB device cannot spare.

`pool_block=False` means that if all 10 sockets for a host are in use the call proceeds
by opening an additional temporary connection rather than blocking the refresh thread. This
trades a small amount of memory for deadlock-freedom, which is correct for a single-device
daemon.

**Memory cost**: each idle socket costs ~8–16 KB of kernel buffer. Ten pools × ten sockets
= 100 potential sockets × ~12 KB ≈ 1.2 MB in the absolute worst case. In practice, most
sockets are closed quickly by the remote server, so real resident overhead is well under
200 KB – acceptable on a 512 MB device.

## Default timeouts

The default timeout is defined in `src/utils/http_utils.py` (line 202):

```python
DEFAULT_TIMEOUT_SECONDS: float = _env_float("INKYPI_HTTP_TIMEOUT_DEFAULT_S", 20.0)
```

The default is **20 seconds** and is read from the environment variable
`INKYPI_HTTP_TIMEOUT_DEFAULT_S`. Optional split timeouts can be set separately:

| Env var | Default | Meaning |
|---|---|---|
| `INKYPI_HTTP_TIMEOUT_DEFAULT_S` | `20.0` | Combined connect+read timeout (seconds) |
| `INKYPI_HTTP_CONNECT_TIMEOUT_S` | unset | Connect-only timeout; overrides default when set |
| `INKYPI_HTTP_READ_TIMEOUT_S` | unset | Read-only timeout; overrides default when set |

### Overriding the timeout per call

Pass `timeout` directly to the session method – it is forwarded to `requests` unchanged:

```python
from utils.http_client import get_http_session

session = get_http_session()

# Tight timeout for a fast API you control
response = session.get(url, timeout=5)

# Split timeout: 5 s to connect, 30 s to read a large payload
response = session.get(url, timeout=(5, 30))
```

### `http_get()` wrapper

`src/utils/http_utils.py` also exposes `http_get()` (line 285) which adds caching,
latency logging, and applies the env-based default automatically. It uses the same shared
session factory as `get_http_session()`, but keeps its thread-local lifecycle because the
request wrapper has different retry defaults. Use it when you want both the pool and
caching without wiring them by hand:

```python
from utils.http_utils import http_get

response = http_get(url, timeout=15)
```

## When to use `http_cache` vs the raw session

| Scenario | Recommendation |
|---|---|
| Fetching data that is valid for minutes (weather, RSS, APOD) | `http_get()` – caching is on by default |
| Fetching the same URL multiple times in one refresh cycle | `http_get()` – second call is free |
| POST / PUT / DELETE (write operations) | `get_http_session().post(...)` – cache skips non-GET by design |
| One-shot reads where stale data would be wrong (live scores, stock prices) | `get_http_session().get(url, timeout=…)` with `use_cache=False` if using `http_get`, or the raw session |
| Streaming a large binary (image download by URL) | `get_http_session().get(url, stream=True, timeout=…)` – cache stores full content, so skip it |

**Decision rule:** if the URL+params combination will be requested more than once in a
single refresh cycle, or if the data is stable for several minutes, reach for `http_get()`.
If you are writing data or consuming a one-shot endpoint, use the raw session directly.

## Plugin author checklist

- **Use `get_http_session()`** (`from utils.http_client import get_http_session`) instead
  of bare `requests.get()` or a new `requests.Session()`. The singleton session is always
  pre-configured with pooling, keep-alive, and retries.
- **Set an explicit timeout** on every call (e.g., `timeout=30`). Never omit it – a hung
  socket will block the refresh thread indefinitely on Pi Zero.
- **Handle `requests.exceptions.ReadTimeout` and `requests.exceptions.ConnectionError`**.
  These are the two most common failures on intermittent home Wi-Fi. Catch them in your
  plugin's `generate_image()` and raise a user-friendly `RuntimeError`.
- **Prefer `http_get()` for repeat reads** – it deduplicates requests automatically and
  respects `Cache-Control` headers from the server.
- **Do not create a bare `requests.Session()`** unless you need a custom adapter (e.g.,
  a custom SSL context or a retry policy different from the shared one). If you must, document
  why in a comment and note it in the PR.

## Example: correct plugin HTTP usage

```python
import requests.exceptions

from utils.http_client import get_http_session


def fetch_data(url: str, api_key: str) -> dict:
    session = get_http_session()
    try:
        resp = session.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ReadTimeout as exc:
        raise RuntimeError("API request timed out") from exc
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError("Could not reach API") from exc
```

## Noted exceptions

`src/plugins/comic/comic_parser.py` (line 94) uses `http_get()` from `src/utils/http_utils.py`
rather than calling `get_http_session()` directly. This is acceptable: `http_get()` is a
higher-level wrapper that internally calls `get_shared_session()` (another pooled session
from `src/utils/http_utils.py`, line 255) and adds caching and latency logging. The comic
parser sets `use_cache=False` because feed content changes frequently; the pool is still
reused.

A follow-up should add a link to this document from `CONTRIBUTING.md` to make it
discoverable for new plugin authors.

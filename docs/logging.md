# Logging

## Default (human-readable)

InkyPi uses Python's standard `logging` module configured via
`src/config/logging.conf`.  Log lines look like:

```
2026-04-08 12:00:00,123 INFO inkypi Starting display refresh
```

## Structured JSON logging

Set `INKYPI_LOG_FORMAT=json` to switch to one-JSON-object-per-line output.
This is opt-in — the default plain-text format is unchanged.

```bash
INKYPI_LOG_FORMAT=json python src/inkypi.py
```

Each line is a valid JSON object with the following fields:

| Field           | Type    | Description                              |
|-----------------|---------|------------------------------------------|
| `ts`            | string  | ISO 8601 UTC timestamp                   |
| `level`         | string  | Log level (`DEBUG`, `INFO`, …)           |
| `logger`        | string  | Logger name                              |
| `msg`           | string  | Formatted log message                    |
| `module`        | string  | Python module name                       |
| `func`          | string  | Function name                            |
| `line`          | integer | Line number                              |
| `pid`           | integer | Process ID                               |
| `extra`         | object  | Any extra fields passed via `extra={}`   |
| `exc_type`      | string  | Exception class name (only on errors)    |
| `exc_message`   | string  | Exception message (only on errors)       |
| `exc_traceback` | string  | Full traceback (only on errors)          |

### Example output

```json
{"ts": "2026-04-08T12:00:00.123456+00:00", "level": "INFO", "logger": "inkypi", "msg": "Starting display refresh", "module": "inkypi", "func": "refresh", "line": 42, "pid": 1234}
```

### Shipping to Loki / Elasticsearch

Because each line is valid JSON you can pipe stdout directly to
[promtail](https://grafana.com/docs/loki/latest/clients/promtail/) or
[Filebeat](https://www.elastic.co/beats/filebeat) without any parsing rules:

```bash
# systemd unit: add to [Service]
Environment=INKYPI_LOG_FORMAT=json
```

### Log level

Set `INKYPI_LOG_LEVEL` (default `INFO`) independently of the format:

```bash
INKYPI_LOG_FORMAT=json INKYPI_LOG_LEVEL=DEBUG python src/inkypi.py
```

### Notes

- No additional dependencies — uses only Python stdlib `json` + `logging`.
- Non-JSON-serialisable extra values are automatically converted to strings.
- Secrets are masked as `***REDACTED***` in both formats, on every handler
  (console, `INKYPI_LOG_FILE` and the dev-mode buffer). The filter covers the
  rendered message, tracebacks, `stack_info` and string `extra={}` values, and
  recognises `api_key=`/`token=`/`password=`/`client_id=`/`appid=`-style
  pairs, credential query parameters (`?key=`, `&sig=`), `Bearer` and
  `Client-ID` header values and bare 32+ character hex strings. The log viewer
  (`/api/logs`, log download, diagnostics) masks journal lines again when it
  reads them. It is pattern-based, so still keep secrets out of log calls.

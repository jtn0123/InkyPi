# Webhook Notifications

InkyPi can POST a JSON payload to one or more webhook URLs whenever a plugin
refresh fails.  This makes it easy to pipe alerts into Slack, Discord,
Pushover, ntfy.sh, or any other service that accepts an HTTP POST.

## Configuration

Add a `webhook_urls` list to your device config (typically via the Settings
page or by editing `device_config.json` directly):

```json
{
  "webhook_urls": [
    "https://hooks.slack.com/services/T000/B000/xxxx",
    "https://ntfy.sh/my-inkypi-alerts"
  ]
}
```

You can provide as many URLs as you like.  Leave the list empty (or omit the
key entirely) to disable webhook notifications.

## Payload

Every webhook receives a JSON body with the following fields:

| Field | Type | Description |
|---|---|---|
| `event` | string | Always `"plugin_failure"` |
| `plugin_id` | string | Internal plugin identifier (e.g. `"weather"`) |
| `instance_name` | string \| null | Human-readable instance name from the playlist |
| `error` | string | Error message from the last failure |
| `ts` | string | ISO-8601 timestamp (device timezone, UTC offset included) |

Example:

```json
{
  "event": "plugin_failure",
  "plugin_id": "weather",
  "instance_name": "Home Weather",
  "error": "ConnectionError: failed to reach api.openweathermap.org",
  "ts": "2026-04-08T14:23:01+00:00"
}
```

## Behaviour

- **Best-effort**: each URL receives exactly one POST attempt.  There are no
  retries.
- **1 second timeout**: a slow webhook endpoint will be abandoned after 1 s so
  it cannot delay the next refresh cycle.
- **Errors are swallowed**: a failed webhook POST is logged at `WARNING` level
  but never raises an exception or affects the display.
- **Circuit-breaker aware**: the webhook fires on every consecutive failure,
  including the failure that triggers the circuit breaker (plugin paused).

## Integrating with ntfy.sh

ntfy.sh accepts plain HTTP POSTs and can forward them to mobile push
notifications.  Create a topic and add its URL:

```json
{
  "webhook_urls": ["https://ntfy.sh/my-secret-inkypi-topic"]
}
```

The JSON body will appear in the notification body.

## Integrating with Slack

Use a Slack incoming webhook URL.  Note that Slack expects a `text` field;
you may need a small intermediary (e.g. a free-tier serverless function or
[Make](https://make.com)) to transform the InkyPi payload into Slack's format.

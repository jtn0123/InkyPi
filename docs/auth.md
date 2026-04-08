# Optional PIN Authentication

InkyPi supports an optional PIN that, when configured, protects all routes
behind a login form. This feature is **off by default** — when no PIN is set
the application behaves identically to before.

## Enabling PIN auth

### Via environment variable (recommended)

```bash
export INKYPI_AUTH_PIN="your-pin-here"
```

Set this in your systemd service file, Docker environment, or shell profile
before starting InkyPi. The PIN is hashed with `hashlib.scrypt` in memory
immediately on startup; the plaintext is never stored or logged.

### Via device config (`device.json`)

Add an `auth` section to your device config:

```json
{
  "auth": {
    "pin": "your-pin-here"
  }
}
```

> **Note:** Storing the PIN in the config file keeps it on disk in plaintext.
> The env-var approach is preferred.

## Behaviour when enabled

- All routes except `/login`, `/logout`, `/sw.js`, `/static/*`, `/api/health`,
  `/healthz`, and `/readyz` redirect unauthenticated users to `/login`.
- A successful login sets a server-side session cookie valid for the browser
  session.
- Failed attempts increment a per-session counter; after **5 consecutive
  failures** the session is locked out for **60 seconds**.
- Visiting `/logout` clears the session and redirects to `/login`.

## Security notes

- Uses `hashlib.scrypt` (stdlib) with a per-process random salt — no new
  dependencies.
- Constant-time comparison via `hmac.compare_digest` prevents timing attacks.
- The PIN hash is stored only in application memory and is regenerated from
  the configured PIN on each startup.
- Sessions are signed by Flask's `SECRET_KEY`. Rotate the secret key if you
  need to invalidate all existing sessions.
- For remote access, combine with HTTPS (see `INKYPI_FORCE_HTTPS`) so the PIN
  is not transmitted in the clear.

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

---

# HTTPS upgrade redirect

InkyPi can transparently redirect plain HTTP requests to HTTPS via a
`before_request` hook in the security middleware.

## Enabling the redirect

Set the following environment variables before starting InkyPi:

```bash
export INKYPI_FORCE_HTTPS=1
# Optional — override the default allow-list of hostnames that may
# appear in the redirect Location header. Comma-separated. Defaults to
# "inkypi.local,localhost,127.0.0.1".
export INKYPI_ALLOWED_HOSTS="inkypi.local,inkypi.example.com"
```

Requests arriving with `X-Forwarded-Proto: https` (e.g. behind a TLS-
terminating reverse proxy) are treated as already-HTTPS and pass through
unchanged. In `--dev` mode the redirect is always skipped regardless of
`INKYPI_FORCE_HTTPS`.

## Host allow-list (JTN-317)

The redirect hook validates the inbound `Host` header against
`INKYPI_ALLOWED_HOSTS` before building the new `Location`. Requests whose
host is not in the allow-list receive a `400 Bad Request` instead of a
redirect. This defends against open-redirect attacks (CodeQL rule
`py/url-redirection`) where an attacker could previously spoof the
`Host` header to have InkyPi emit `Location: https://evil.example/`.

When the server is reached by a hostname that is not in the default
allow-list (for example a custom mDNS name or a public DNS record), add
it to `INKYPI_ALLOWED_HOSTS` — otherwise all HTTP traffic will be
rejected with a 400.

---

# Read-only API Token (JTN-477)

InkyPi supports an optional read-only bearer token for monitoring scripts and
automation tools that need to poll status endpoints without requiring an
interactive PIN session. This feature is **independent** from PIN auth and can
be used whether or not a PIN is configured.

## Enabling the read-only token

Set the `INKYPI_READONLY_TOKEN` environment variable before starting InkyPi:

```bash
export INKYPI_READONLY_TOKEN="your-long-random-token-here"
```

Use a cryptographically strong random value, for example:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

The token is hashed with `hashlib.sha256` immediately on startup; the
plaintext is never stored or logged.

## Using the token

Pass the token in the `Authorization` header of your HTTP request:

```bash
curl -H "Authorization: Bearer <your-token>" http://inkypi.local:5000/api/uptime
```

## Allowed endpoints and methods

The token grants **read-only** access (GET / HEAD / OPTIONS only) to the
following paths:

| Path               | Description                  |
|--------------------|------------------------------|
| `/api/health`      | Service health check         |
| `/api/version/info`| Firmware / app version       |
| `/api/uptime`      | Device uptime                |
| `/api/screenshot`  | Current display screenshot   |
| `/metrics`         | Prometheus-style metrics     |
| `/api/stats`       | Refresh statistics           |

Requests to any other path, or any mutating method (POST, PUT, DELETE, PATCH)
on the above paths, are **not** authorised by the token — a PIN session is
required.

## Security notes

- The raw token is never stored; only its SHA-256 hex digest is kept in
  application memory.
- Comparison uses `hmac.compare_digest` to prevent timing attacks.
- Combine with HTTPS so the token is not transmitted in the clear.
- To rotate the token, restart InkyPi with a new `INKYPI_READONLY_TOKEN` value.
- PIN auth and bearer-token auth are independent: having a valid token does
  **not** grant access to admin or mutating routes.

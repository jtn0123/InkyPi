# Authentication and HTTPS commissioning

The web server listens on all interfaces. **PIN authentication is off by
default**: any reachable client can administer the display unless a PIN is
configured. A read-only token alone does not turn authentication on. Keep this
mode on a trusted LAN; do not expose it directly to the Internet.

For authenticated access, configure a PIN and, for remote access, a TLS reverse
proxy. `INKYPI_FORCE_HTTPS` redirects requests; it does not provide TLS itself.

## Persistent configuration for the installed service

Shell-profile exports affect a shell-launched development process, not the
installed systemd service. Create a root-readable environment file:

```bash
sudo install -m 600 /dev/null /etc/inkypi-security.env
sudoedit /etc/inkypi-security.env
```

Add these settings, replacing the example PIN locally:

```ini
INKYPI_AUTH_PIN=replace-with-a-long-random-PIN
```

Then run `sudo systemctl edit inkypi` and add:

```ini
[Service]
EnvironmentFile=/etc/inkypi-security.env
```

Apply it:

```bash
sudo systemctl daemon-reload
sudo systemctl restart inkypi
curl -I http://inkypi.local/settings
```

The unauthenticated request must redirect to `/login`. Public health/static
routes intentionally remain available. Verify an administration route, rather
than using a health response as evidence that authentication is enabled.

Environment files and `device.json` values are plaintext on disk. Protect their
permissions and backups. InkyPi hashes the PIN with scrypt in process memory;
it does not remove the source value from the environment or config. The
alternative `auth.pin` configuration in `device.json` has the same at-rest
consideration.

## HTTPS profile and direct proxy trust

Add these to the same environment file for a TLS proxy running on the Pi:

```ini
INKYPI_FORCE_HTTPS=1
INKYPI_ALLOWED_HOSTS=inkypi.local,inkypi.example.com
INKYPI_TRUSTED_PROXIES=127.0.0.1/32,::1/128
```

Use the actual direct proxy IP/CIDR if it runs elsewhere. Broad unrestricted
networks are rejected at startup. The trusted proxy must overwrite
`X-Forwarded-Proto` with a single `https` or `http` value, preserve the intended
Host, and strip client-supplied forwarded headers. InkyPi trusts only the scheme
from a configured direct peer; it does not reinterpret forwarded host, port,
path or client address. Block direct external access to the backend port with
your proxy/firewall configuration.

The HTTPS profile enables **Secure, HttpOnly, SameSite=Lax session cookies**.
HSTS is emitted only for HTTPS or the accepted proxy scheme. An arbitrary
client's `X-Forwarded-Proto: https` cannot bypass the redirect. Unknown redirect
hosts receive 400; configure every intended hostname in `INKYPI_ALLOWED_HOSTS`.
`INKYPI_SECURE_COOKIES=1` can enable Secure cookies independently when TLS is
already enforced elsewhere. Dev mode skips the forced redirect; normal LAN
HTTP remains available when the HTTPS profile is disabled.

After restarting, verify both boundaries:

```bash
# Direct HTTP with a spoofed header must still redirect to HTTPS when the
# request does not originate from a configured proxy peer.
curl -I -H 'X-Forwarded-Proto: https' http://inkypi.local/settings
# The real HTTPS login response must include Secure on any session cookie.
curl -I https://inkypi.example.com/login
```

A local curl from a trusted loopback peer intentionally receives proxy trust;
run the spoof test from an untrusted LAN host. Review firewall restrictions
separately from application tests.

## PIN sessions

All administration routes require login when the PIN is configured. The login
uses a signed **client-side Flask session cookie**, not a server-side session
store. Treat its contents as visible to the browser; signing prevents edits,
not disclosure. The persistent `SECRET_KEY` signs it; rotating the key
invalidates existing sessions. `/logout` clears the session.

PIN comparisons use constant-time verification. Repeated failures are limited
by session and client IP; after five session failures, the session is locked
for 60 seconds. HTTPS protects PIN transmission; hashing alone does not.

## Read-only monitoring token

With PIN authentication enabled, `INKYPI_READONLY_TOKEN` allows monitoring
without an interactive session. Store a strong random token in the protected
environment file and restart the service. Its hash is retained in memory; the
configured source remains plaintext at rest. A token does not authorize admin
or mutating routes. **Without a PIN, administration remains unauthenticated
regardless of this token.**

Allowed methods are GET/HEAD/OPTIONS on these paths:

| Path | Purpose |
|------|---------|
| `/api/health` | Service health |
| `/api/version/info` | Version |
| `/api/uptime` | Uptime |
| `/api/screenshot` | Display screenshot |
| `/metrics` | Metrics |
| `/api/stats` | Refresh statistics |

```bash
curl -H 'Authorization: Bearer <your-token>' https://inkypi.example.com/api/uptime
```

For trusted LAN HTTP, the production default is port 80
(`http://inkypi.local/api/uptime`); development defaults to 8080. Use HTTPS when
transmitting a token over an untrusted network. To rotate it, update the
protected environment file and restart the service.

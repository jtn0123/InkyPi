# Security

## Allowed Host names (DNS-rebinding protection)

Every request must name this device in its `Host` header, otherwise InkyPi
answers `400 Invalid host`. This stops DNS rebinding, where a web page you
visit points its own domain at the Pi's LAN address so it can read and post to
the InkyPi UI as if it were the same site. The check is always on, with or
without a PIN and the HTTPS profile.

Accepted without configuration (case-insensitive, any port):

- any IPv4 or IPv6 address literal, such as `192.168.1.42`, `127.0.0.1` or
  `[::1]:8080`
- `localhost`, `inkypi` and `inkypi.local`
- the Pi's own hostname from `hostname`, bare and with `.local` (for a Pi
  named `kitchen`, `kitchen` and `kitchen.local`)

Any other name you use to reach the Pi, such as a DNS name on your router, a
reverse-proxy hostname or a Tailscale MagicDNS name, must be added to
`INKYPI_ALLOWED_HOSTS` in the service environment file described in
[auth.md](auth.md). The value is a comma-separated list, without ports, and
adds to the defaults above:

```ini
INKYPI_ALLOWED_HOSTS=inkypi.home.arpa,frame.example.com
```

Restart the service after changing it. The same list decides which hosts the
HTTPS profile redirects (see [auth.md](auth.md)).

## Sessions

With a PIN configured, a login lasts at most 30 days and ends as soon as the
PIN changes, even if the browser keeps its cookie. Restarting InkyPi with the
same PIN and `SECRET_KEY` keeps existing logins. Set
`INKYPI_SESSION_MAX_AGE_DAYS` (a positive number, fractions allowed) to change
the lifetime. Webhook notifications log only the scheme and host of each
webhook URL, never the path or query that carries its token.

## Service sandbox

`inkypi.service` runs as root because it drives the display over SPI and GPIO,
reboots the Pi and starts updates. The installer adds a systemd drop-in,
`/etc/systemd/system/inkypi.service.d/hardening.conf`, that makes the rest of
the filesystem read-only to the service. A bug or a hostile plugin can't
rewrite `/etc`, `/usr`, `/boot`, the venv or InkyPi's own code. The service can
write only to:

- `/usr/local/inkypi`, for `.env` (API keys and `SECRET_KEY`)
- `src/config` and `src/static/images` in the checkout
- `runtime/` in the checkout, for the benchmarks database
- `/var/lib/inkypi` and `/run/inkypi`, for update, boot and crash state
- root's `.cache`, `.config`, `.pki` and `.local`, for Chromium and fontconfig

It also gets a private `/tmp`, can't gain privileges through setuid programs
and can't load kernel modules or change kernel settings. Updates still work:
the app hands them to `systemd-run`, which runs them as a separate unit
outside the sandbox.

This is a speed bump, not a wall. The service is still root, and it can still
ask systemd to run commands outside the sandbox, which is how updates work.
Running it as an unprivileged user would close that gap.

The installer rewrites `hardening.conf` on every install and update, with this
device's paths. To loosen it on one device, add a later drop-in instead, for
example `/etc/systemd/system/inkypi.service.d/zz-local.conf`:

```ini
[Service]
ReadWritePaths=/home/pi/extra-folder
```

Then run `sudo systemctl daemon-reload && sudo systemctl restart inkypi`.

## Remote-page rendering

The Screenshot plugin accepts public HTTP/HTTPS websites. Its Chromium process
uses a fresh temporary profile, receives a minimal environment without provider
keys or application secrets, and retains Chromium's sandbox and web security.
When InkyPi runs as root, the remote browser drops to the system `nobody` account
with no supplementary groups. Local HTML templates use a separate rendering
path; their file-access permissions are never applied to remote pages.

A per-render loopback proxy validates all DNS answers and connects to a validated
numeric IP for each remote connection, including redirects and subresources.
Private, loopback, link-local and non-global addresses are rejected. Chromium's
implicit loopback proxy bypass is disabled, with no direct proxy fallback; QUIC
and non-proxied WebRTC UDP are disabled. HTTPS tunnels are limited to port 443,
and plain WebSocket upgrades are unsupported. Private dashboards and custom-port
HTTPS sites therefore cannot be captured by this plugin.

For remote capture, `chromium-headless-shell` is preferred when installed; it
avoids full Chrome's desktop initialization. On Debian/Pi OS, install it with
`sudo apt install chromium-headless-shell` if the full Chromium backend hangs.
The browser must be installed and its sandbox must work for the unprivileged
account. Failure returns a rendering error; there is no fallback to an
unsandboxed remote browser. On Raspberry Pi, test a public Screenshot playlist
after upgrading and check the service log if Chromium cannot start. Desktop and
simulated checks do not establish a physical-Pi sandbox or memory-pressure pass.
The proxy is an application-level egress boundary, not a separate network
namespace or protection against a compromised Chromium network process.

Chromium documents [proxy behavior and loopback bypass rules](https://chromium.googlesource.com/chromium/src/+/main/net/docs/proxy.md).

## Server-side fetches of user URLs

Plugins that download a user-supplied URL on the Pi (Image URL, Image Album,
remote images, RSS and Calendar) validate the URL before connecting: the
scheme must be HTTP/HTTPS and every address the hostname resolves to must be
public, by the same rule the Screenshot proxy above applies. Private,
shared (`100.64.0.0/10`, which carrier NAT and Tailscale use), loopback,
link-local, documentation, benchmarking, reserved and multicast addresses are
refused, as are the deprecated 6to4 relay prefix `192.88.99.0/24` and IPv6
outside `2000::/3` or inside the 6to4 and Teredo tunnel prefixes.

The connection is pinned to the addresses that were checked, so a DNS answer
that changes between the check and the request cannot redirect it. A host
name with non-ASCII letters, such as `exämple.com`, is checked and pinned in
the ASCII form the request looks up (`xn--exmple-cua.com`). While a request
is pinned, any other name it tries to look up is refused rather than
resolved. Redirects are not followed automatically. Each `Location` target,
including relative ones, is checked and pinned in the same way, with a limit
of 5 hops. A public site that redirects to `192.168.x.x`, `127.0.0.1` or a
cloud metadata address is refused. When a redirect leaves the original scheme,
host and port, only the `User-Agent` and `Accept` headers go with it;
credentials such as `Authorization`, cookies and Immich's `x-api-key` are
dropped.

Image Album's Immich API calls don't follow redirects at all. If Immich
answers one, the refresh fails, the service log names the redirect, and the
API key is never sent to its target. Set the Base URL to the address Immich
is actually served from, for example `https://` rather than `http://`.

RSS and Calendar downloads are streamed with a size cap: 5 MB for a feed and
10 MB for an `.ics` file. Larger responses fail the refresh and nothing is
rendered from them.

RSS item images (`media:content`, `media:thumbnail`, enclosures) are fetched
by InkyPi through the same guard, never by the rendering browser. Only the
items that are rendered (at most 10) are fetched, each capped at 2 MB and
25 megapixels within a 20-second total budget. Each image is re-encoded
as a small JPEG and embedded in the page. An image that fails the guard,
times out or does not decode is left out; the story still renders. The local
template renderer's Content-Security-Policy allows only `file:`, `data:` and
`blob:` images, so a template cannot make Chromium load a remote image.
Third-party plugin templates that referenced remote `<img>` URLs must fetch
them in Python the same way.

### Servers on your local network or Tailscale (opt-in)

RSS, Calendar, Image URL and Image Album refuse private-network addresses by
default. When one is configured, the plugin shows an error that names the
setting below. To fetch from a server on your LAN, such as Nextcloud,
Radicale or Immich on `192.168.x.x`, or one you reach over Tailscale on
`100.x.y.z`, opt in for the deployment. Add the setting to the service
environment file described in [auth.md](auth.md) and restart:

```ini
INKYPI_ALLOW_PRIVATE_FEEDS=1
```

The opt-in admits only site-local ranges: `10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`, shared address space `100.64.0.0/10` (Tailscale) and IPv6
unique-local `fc00::/7` (which holds Tailscale's IPv6 range). Loopback
(`localhost`, `127.0.0.1`, `::1`), link-local and cloud-metadata
(`169.254.0.0/16`), unspecified, reserved and multicast addresses stay
blocked. To use a calendar server running on the Pi itself, give its LAN
address instead of `localhost`. The setting affects RSS, Calendar, Image URL
and Image Album (Immich). Screenshot and the plugins that fetch from fixed
public services are unchanged. Enable it only if everyone who can edit plugin
settings may make the Pi send requests to hosts on your network.

## Backups

**Settings → Backup** leaves secrets out unless **Include API keys** is on,
which needs a PIN (see [auth.md](auth.md)). A backup without keys has no API
keys, no `auth` section (where `device.json` can hold the PIN) and no
`webhook_urls`, whose links carry each service's token.

Restoring a backup changes only what the backup holds. A backup without keys
leaves this device's API keys, PIN and webhooks as they are. A backup with
keys puts back its PIN and webhook list when it has them; InkyPi reads the
PIN when it starts, so restart it to use the restored one. A PIN set with
`INKYPI_AUTH_PIN` in the service environment still takes precedence.

## Software Bill of Materials (SBOM)

Every GitHub release includes a CycloneDX JSON SBOM attached as a release asset named
`inkypi-vX.Y.Z-bom.json`. This file lists all Python packages bundled with that release
so that security teams and auditors can inventory third-party dependencies.

### Downloading the SBOM

```bash
# Replace vX.Y.Z with the release tag, e.g. v0.39.8
gh release download vX.Y.Z --repo jtn0123/InkyPi --pattern 'inkypi-vX.Y.Z-bom.json'
```

Or download it directly from the GitHub releases page:
`https://github.com/jtn0123/InkyPi/releases`

### Validating the SBOM with cyclonedx-cli

Install the [CycloneDX CLI](https://github.com/CycloneDX/cyclonedx-cli):

```bash
# macOS (Homebrew)
brew install cyclonedx/cyclonedx/cyclonedx-cli

# Or download a binary from:
# https://github.com/CycloneDX/cyclonedx-cli/releases
```

Validate the SBOM is well-formed:

```bash
cyclonedx-cli validate --input-file inkypi-vX.Y.Z-bom.json --input-format json
```

Convert to other formats (e.g. SPDX):

```bash
cyclonedx-cli convert \
  --input-file inkypi-vX.Y.Z-bom.json \
  --input-format json \
  --output-file inkypi-vX.Y.Z-bom.spdx \
  --output-format spdxtag
```

### Checking for known vulnerabilities

From the repository root, use the committed development environment and audit
the locked requirement files: the runtime and dev exports, and the installer's
own files (pip, uv and the GPIO libraries). Every file is fully hashed, so
pip-audit checks the pins as written, for every platform, without installing
anything:

```bash
source scripts/venv.sh
scripts/audit_dependencies.sh --strict
```

It writes one JSON report per file to `artifacts/security/` and lists each
finding with the version that fixes it.

pip-audit checks the files against a live advisory feed, so a new advisory can
turn CI red with no code change. CI's **Security and SBOM** job therefore runs
it strictly only where a finding is something to act on:

- a pull request that changes `uv.lock` or an `install/*requirements*.txt` file;
- the nightly run, and a manual run.

Other pull requests and pushes to `main` report a finding as a warning, so an
advisory doesn't block unrelated merges or the release. Fix it in a pull
request that updates the package. GitHub's Dependabot alerts report the same
advisories.

Generate a CycloneDX inventory separately:

```bash
python -m cyclonedx_py environment .venv/bin/python --of JSON -o sbom.json
```

An SBOM describes installed packages; generating or converting it does not
perform the vulnerability audit above. The optional cyclonedx-cli conversion
example requires that separate tool to be installed. These commands match CI's
audit and inventory tools.

## Security Reporting

To report a vulnerability, please open a [GitHub Security Advisory](https://github.com/jtn0123/InkyPi/security/advisories/new)
or email the maintainers directly rather than filing a public issue.

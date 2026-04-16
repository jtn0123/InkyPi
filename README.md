<div align="center">

# InkyPi

### Your content, on paper. An open-source E-Ink display powered by Raspberry Pi.

[![CI](https://github.com/jtn0123/InkyPi/actions/workflows/ci.yml/badge.svg)](https://github.com/jtn0123/InkyPi/actions/workflows/ci.yml)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=jtn0123_InkyPi&metric=alert_status)](https://sonarcloud.io/summary/overall?id=jtn0123_InkyPi)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: GPL v3](https://img.shields.io/badge/license-GPL%20v3-green)](./LICENSE)

<br>

<img src="./docs/images/inky_clock.jpg" alt="InkyPi e-ink display showing a clock face in a wooden picture frame" width="600" />

<br>

**No glare. No backlight. No notifications. Just the content you care about.**

[Getting Started](#quick-start) · [Plugins](#plugins) · [Hardware](#hardware) · [Docs](#documentation)

</div>

---

## Why InkyPi?

<table>
<tr>
<td width="50%">

**Paper-like display** — crisp, minimalist visuals that are easy on the eyes, with no glare or backlight

**Web-based control** — configure and update the display from any device on your network

**20+ built-in plugins** — clocks, weather, news, calendars, AI-generated art, and more

</td>
<td width="50%">

**Scheduled playlists** — rotate different plugins on a schedule throughout the day

**Fully open source** — modify, customize, and create your own plugins

**Beginner-friendly** — one-command install, runs on a Raspberry Pi Zero 2 W and up

</td>
</tr>
</table>

---

## Quick Start

```bash
git clone https://github.com/jtn0123/InkyPi.git
cd InkyPi
sudo bash install/install.sh
```

After install, reboot your Pi and the InkyPi splash screen appears. Open the web interface from any device on your network to configure plugins.

> For Waveshare displays, pass the model: `sudo bash install/install.sh -W epd7in3f`

For detailed setup including Raspberry Pi OS imaging, see [installation.md](./docs/installation.md) or watch the [YouTube tutorial](https://youtu.be/L5PvQj1vfC4).

---

## Plugins

| Category | Plugins |
|----------|---------|
| **Display** | Clock · Countdown · Year Progress · Todo List |
| **Images** | Image Upload · Image Album · Image Folder · Image URL · Unsplash · NASA APOD · Wikipedia POTD |
| **News & Media** | Newspaper Front Pages · Daily Comics · RSS Feeds |
| **Information** | Weather · Calendar (Google / Outlook / Apple) · GitHub Stats |
| **AI** | AI Image Generation · AI Text Generation (OpenAI) |
| **Utility** | Screenshot (capture any URL) |

Want to build your own? See [Building InkyPi Plugins](./docs/building_plugins.md).

---

## Hardware

**Raspberry Pi** — Pi 4, Pi 3, or Zero 2 W (40-pin header recommended)

**MicroSD Card** — 8 GB minimum ([example](https://amzn.to/3G3Tq9W))

**E-Ink Display:**

| Brand | Supported Models |
|-------|-----------------|
| **Pimoroni Inky Impression** | [13.3"](https://collabs.shop/q2jmza) · [7.3"](https://collabs.shop/q2jmza) · [5.7"](https://collabs.shop/ns6m6m) · [4"](https://collabs.shop/cpwtbh) |
| **Pimoroni Inky wHAT** | [4.2"](https://collabs.shop/jrzqmf) |
| **Waveshare Spectra 6 (E6)** | [4"](https://www.waveshare.com/4inch-e-paper-hat-plus-e.htm?&aff_id=111126) · [7.3"](https://www.waveshare.com/7.3inch-e-paper-hat-e.htm?&aff_id=111126) · [13.3"](https://www.waveshare.com/13.3inch-e-paper-hat-plus-e.htm?&aff_id=111126) |
| **Waveshare B&W** | [7.5"](https://www.waveshare.com/7.5inch-e-paper-hat.htm?&aff_id=111126) · [13.3"](https://www.waveshare.com/13.3inch-e-paper-hat-k.htm?&aff_id=111126) |

See [all Waveshare displays](https://www.waveshare.com/product/raspberry-pi/displays/e-paper.htm?&aff_id=111126) or their [Amazon store](https://amzn.to/3HPRTEZ). IT8951-based displays are not supported. See [Waveshare compatibility](#waveshare-display-support) for details.

**Frame** — picture frame or 3D-printed stand. See [community builds](./docs/community.md) for inspiration.

> **Disclosure:** Hardware links above are affiliate links that help support the project, at no extra cost to you.

---

## What's New in This Fork

This fork is **1,100+ commits** ahead of upstream, transforming InkyPi from a functional prototype into a production-grade, security-hardened system. Active development continues with a focus on reliability, security, and developer experience.

### Security

| Feature | Details |
|---------|---------|
| SSRF & DNS Rebinding Protection | DNS-pinned URL fetches block rebinding attacks |
| Content Security Policy (CSP) | Nonce-based CSP eliminates inline script violations |
| XSS Prevention | Systematic closure across 8+ blueprints |
| Open-Redirect Defense | Host allow-list validation with safe URL rebuilding |
| Path Traversal Protection | Input validation across all endpoints |
| CSRF Token Validation | Per-request validation with secure token generation |
| Rate Limiting | Token-bucket & sliding-window per-IP limits on auth/refresh/mutating endpoints |
| Supply-Chain Integrity | Hash-pinned lockfiles (`--require-hashes`), SBOM, dependency license audit |
| Secret Management | Persistent, entropy-rich SECRET_KEY bootstrap; secrets redacted from logs |

### Testing

| Feature | Details |
|---------|---------|
| End-to-End Journey Tests | First-run setup, API key CRUD, playlist management, plugin preview, update flow (Playwright) |
| UI Audit Suite | Click sweeps, element overlap detection, responsive mobile tests, toggle state reflection |
| Snapshot/Golden-File Testing | Plugin image output comparison for visual regressions |
| Accessibility Testing | Axe-core scans integrated into Playwright |
| Contract Tests | JSON response shape validation for 20+ endpoints |
| Chaos Testing | RefreshTask error-injection paths |
| Memory Gate | Peak RSS sampling and 512 MB smoke tests for Pi Zero 2 W |
| Benchmark Regression Gate | Performance regression detection in CI |
| Install Crash-Loop Gate | Prevents runaway restart bugs from merging |

### Install & Update System

| Feature | Details |
|---------|---------|
| One-Command Update | `do_update.sh` with semver tag resolution |
| Rollback Support | `prev_version` breadcrumb for atomic rollback |
| Update Failure Surfacing | Errors visible in the web UI, not just logs |
| Atomic Install | File-level atomicity with `flock` guard against concurrent installs |
| Pre-Built Wheels | Release asset wheelhouse accelerates install on Pi |
| uv Migration | Faster dependency resolution, lighter installs vs pip |
| Install Matrix | CI tests across Bookworm, Bullseye, and Trixie (arm64) |
| Waveshare Driver Pinning | Locked driver versions for stability |

### UI/UX

| Feature | Details |
|---------|---------|
| HTMX Form Submission | Non-blocking plugin settings save with inline feedback |
| In-App Modals | Replaced `window.confirm()` with accessible dialog modals |
| Floating Debug Console | Client-side log viewer for troubleshooting |
| System Health Dashboard | Status badge wired to `/api/diagnostics` |
| Plugin Breadcrumbs | Navigation context and plugin chip display |
| Form Validation | Toast notifications naming the failing field |
| Progress Feedback | Visible button states for all async operations |
| Time Input Picker | Native HTML5 input for playlist scheduling |
| API Keys Management UI | Centralized key management for plugins |
| Image History with Pagination | Browse and manage display history |

### Accessibility

| Feature | Details |
|---------|---------|
| Dialog Semantics | `role="dialog"`, Escape key handling, focus management |
| ARIA Labels | Descriptive labels on icons, rows, buttons, toggle states |
| Keyboard Navigation | Full keyboard support across modals and forms |
| Skip-to-Content Link | Standard navigation landmark |
| Automated Testing | Axe-core scans in CI prevent regressions |

### Performance & Reliability

| Feature | Details |
|---------|---------|
| Lazy Module Imports | Reduced startup memory footprint |
| Low-Memory Image Loading | Memory-efficient image ops for preview plugins |
| HTTP Cache with LRU Eviction | Bounded memory growth for cached responses |
| Async Job Queue | Non-blocking plugin renders |
| Systemd Hardening | `StartLimitBurst`, `OOMScoreAdjust`, failure service |
| Multi-threaded Server | Concurrent request handling |

### CI/CD Pipeline

| Feature | Details |
|---------|---------|
| Security Scanning | CodeQL, Semgrep, Trivy, GitLeaks, dependency review |
| Browser Smoke Tests | Mandatory CI gate for UI regressions |
| Memory Diff Comments | Per-PR startup memory impact analysis |
| Nightly OS Drift Detector | Catches breakage from system package updates |
| CycloneDX SBOM | Software bill of materials as release asset |
| Snapshot Artifact Upload | PNG diffs on test failure for visual debugging |

### Developer Experience

| Feature | Details |
|---------|---------|
| Watch-Mode CSS Rebuild | Live asset rebuild during development |
| Dev-Mode Response Validator | Middleware schema enforcement (no-op in prod) |
| Docker Install Simulation | Multi-base Dockerfile testing |
| Benchmark Compare Script | Performance regression analysis |
| 22 Plugins (vs 14 upstream) | 8 additional built-in plugins |

---

## Update

```bash
cd InkyPi
sudo bash install/do_update.sh
```

Pin a specific version: `sudo bash install/do_update.sh v0.51.6`

The web UI's "Update" button uses the same path. For branch tracking, use `git pull` then `sudo bash install/update.sh`.

---

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r install/requirements-dev.txt
.venv/bin/python src/inkypi.py --dev --web-only
```

Dev server runs on port 8080. See [CONTRIBUTING.md](./CONTRIBUTING.md) and [development.md](./docs/development.md) for full details.

### Testing

```bash
scripts/test.sh                                        # fast local test runner (sharded)
scripts/test.sh tests/unit/test_refresh_task_stress.py  # single file
scripts/preflash_validate.sh                            # hardware-free pre-flash gate
```

See [testing.md](./docs/testing.md) for coverage and CI details.

### Install Verification (Docker)

```bash
./scripts/sim_install.sh trixie     # Debian Trixie (default)
./scripts/sim_install.sh bookworm   # Debian Bookworm
./scripts/sim_install.sh bullseye   # Debian Bullseye
```

Builds an arm64 container capped at 512 MB RAM (matching Pi Zero 2 W) and runs `install.sh` end-to-end.

---

## Uninstall

```bash
sudo bash install/uninstall.sh
```

---

## Waveshare Display Support

Waveshare displays require model-specific drivers from their [Python EPD library](https://github.com/waveshareteam/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd). IT8951-based displays are not supported, and screens smaller than 4" are not recommended.

When installing, use `-W` with your model name (without `.py`): `sudo bash install/install.sh -W epd7in3f`

---

## Documentation

- [Architecture](./docs/architecture.md) — Component map and request/refresh flow
- [Development Setup](./docs/development.md) — Local dev on macOS, Linux, or Windows
- [API Keys](./docs/api_keys.md) — Configuring keys for OpenAI, Google, etc.
- [Testing](./docs/testing.md) — Test suite, sharding, browser tests, coverage
- [Building Plugins](./docs/building_plugins.md) — Create custom plugins (includes hello-world)
- [Troubleshooting](./docs/troubleshooting.md) — Common issues and fixes

---

## Issues

Check the [troubleshooting guide](./docs/troubleshooting.md) first. If you're still stuck, open an issue on [GitHub Issues](https://github.com/jtn0123/InkyPi/issues).

> Pi Zero W users: see [Known Issues during Pi Zero W Installation](./docs/troubleshooting.md#known-issues-during-pi-zero-w-installation).

## License

GPL 3.0 — see [LICENSE](./LICENSE). Font and icon attribution: [attribution.md](./docs/attribution.md).

---

<div align="center">

Forked from [fatihak/InkyPi](https://github.com/fatihak/InkyPi)

</div>

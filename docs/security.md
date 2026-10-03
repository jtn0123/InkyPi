# Security

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

Chromium documents [proxy behavior and loopback bypass rules](https://github.com/chromium/chromium/blob/main/net/docs/proxy.md).

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
the locked requirement files:

```bash
source scripts/venv.sh
python -m pip_audit -r install/requirements.txt --format=json --output runtime-audit.json
python -m pip_audit -r install/requirements-dev.txt --format=json --output dev-audit.json
```

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

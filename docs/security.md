# Security

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

```bash
pip install pip-audit
pip-audit --sbom inkypi-vX.Y.Z-bom.json
```

## Security Reporting

To report a vulnerability, please open a [GitHub Security Advisory](https://github.com/jtn0123/InkyPi/security/advisories/new)
or email the maintainers directly rather than filing a public issue.

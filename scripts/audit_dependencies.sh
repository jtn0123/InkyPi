#!/usr/bin/env bash
# Check the locked requirement files for known vulnerabilities with pip-audit.
#
# Usage: scripts/audit_dependencies.sh [--strict]
#
# Writes one JSON report per file to artifacts/security/ and lists every
# finding. With --strict, a finding (or an audit that can't finish) exits 1.
# Without it, findings are reported as a warning and the script exits 0. CI
# uses that for pull requests that don't change a dependency file, so an
# advisory published elsewhere doesn't hold up unrelated work (see
# docs/security.md#checking-for-known-vulnerabilities).
#
# Run it from the dev venv: pip-audit is pinned in install/requirements-dev.txt.
set -euo pipefail

strict=0
case "${1:-}" in
    --strict) strict=1 ;;
    "") ;;
    *)
        echo "usage: $0 [--strict]" >&2
        exit 2
        ;;
esac

out_dir=artifacts/security
mkdir -p "$out_dir"
failed=()

# Every file is fully pinned and hashed, so --disable-pip checks the pins as
# written, without installing anything. That covers the pins for every
# platform, including the Pi-only packages that an install on this machine
# would skip.
audit() {
    local name="$1"
    local file="$2"
    if ! python -m pip_audit --disable-pip -r "$file" --format=json \
        --output "$out_dir/pip-audit-$name.json"; then
        failed+=("$name")
    fi
}

audit runtime install/requirements.txt
audit dev install/requirements-dev.txt
# What install.sh and update.sh install as root before the app's own
# requirements.
for name in bootstrap uv ws; do
    audit "$name" "install/${name}-requirements.txt"
done

if [ "${#failed[@]}" -eq 0 ]; then
    echo "pip-audit: no known vulnerabilities in any locked requirement file."
    exit 0
fi

python -I - "$out_dir" "${failed[@]}" <<'PY'
import json
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
for name in sys.argv[2:]:
    try:
        report = json.loads((out_dir / f"pip-audit-{name}.json").read_text())
    except (OSError, ValueError):
        print(f"{name}: no report; the audit did not finish (see its output above)")
        continue
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            fixed_in = ", ".join(vuln.get("fix_versions", [])) or "no fix yet"
            print(
                f"{name}: {dep.get('name')} {dep.get('version', '?')}: "
                f"{vuln.get('id')} (fixed in: {fixed_in})"
            )
PY

message="pip-audit reported findings, or could not finish, for: ${failed[*]}"
if [ "$strict" -eq 1 ]; then
    echo "::error title=Known vulnerabilities::${message}."
    exit 1
fi
echo "::warning title=Known vulnerabilities (not blocking)::${message}. This change doesn't touch a dependency file, so it isn't held up. Update the affected package in its own pull request."

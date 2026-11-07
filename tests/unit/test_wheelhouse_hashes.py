"""Wheelhouse wheels must be installable under --require-hashes.

Regression: requirements.txt pins PyPI hashes only, so the CI-built
linux_armv7l wheels for numpy/Pillow/cffi were rejected and a Pi Zero 2 W
compiled them from source mid-update until the watchdog reset it.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
NUMPY_PYPI = "a" * 64
NUMPY_PI = "b" * 64
PILLOW_PI = "c" * 64
PURE = "d" * 64

REQUIREMENTS = f"""\
# header comment
numpy==2.5.4 ; python_full_version >= '3.13' \\
    --hash=sha256:{NUMPY_PYPI}
    # via inkypi
pillow==13.0.0 \\
    --hash=sha256:{"e" * 64}
requests==2.34.2 \\
    --hash=sha256:{PURE}
"""

MANIFEST = f"""\
{NUMPY_PI}  numpy-2.5.4-cp313-cp313-linux_armv7l.whl
{PILLOW_PI}  pillow-13.0.0-cp313-cp313-linux_armv7l.whl
{PURE}  requests-2.34.2-py3-none-any.whl
{"f" * 64}  numpy-2.4.0-cp313-cp313-linux_armv7l.whl
not-a-hash  junk.whl
"""


@pytest.fixture
def helper() -> ModuleType:
    path = REPO / "install" / "_wheelhouse_hashes.py"
    spec = importlib.util.spec_from_file_location("_wheelhouse_hashes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hashes_for(text: str, pin: str) -> set[str]:
    """Collect the sha256 values attached to the requirement starting with *pin*."""
    found: set[str] = set()
    inside = False
    for line in text.splitlines():
        if line.startswith(pin):
            inside = True
        elif line and not line.startswith(" "):
            inside = False
        if inside:
            found.update(
                part.split("sha256:")[1].rstrip(" \\")
                for part in line.split()
                if part.startswith("--hash=sha256:")
            )
    return found


def test_matching_pins_accept_wheelhouse_hashes(helper: ModuleType) -> None:
    text, count = helper.extend_requirements(
        REQUIREMENTS, helper.manifest_hashes(MANIFEST)
    )
    assert count == 2
    assert _hashes_for(text, "numpy==") == {NUMPY_PYPI, NUMPY_PI}
    assert _hashes_for(text, "pillow==") == {"e" * 64, PILLOW_PI}
    # Same hash already pinned: nothing added. Other versions never leak in.
    assert _hashes_for(text, "requests==") == {PURE}
    assert "f" * 64 not in text
    assert "# via inkypi" in text and text.endswith("\n")


def test_output_is_valid_for_uv_require_hashes(
    helper: ModuleType, tmp_path: Path
) -> None:
    text, _ = helper.extend_requirements(REQUIREMENTS, helper.manifest_hashes(MANIFEST))
    req = tmp_path / "req.txt"
    req.write_text(text)
    pip = subprocess.run(
        ["uv", "pip", "compile", "--no-header", "--quiet", str(req)],
        capture_output=True,
        text=True,
        check=False,
    )
    if pip.returncode == 127:
        pytest.skip("uv not installed")
    # Parsing is what matters here: a broken continuation line would make uv
    # read "--hash=..." as a requirement and fail before resolution.
    assert "--hash" not in pip.stderr, pip.stderr


def test_name_normalization(helper: ModuleType) -> None:
    hashes = helper.manifest_hashes(f"{PURE}  python_dotenv-1.2.4-py3-none-any.whl\n")
    text, count = helper.extend_requirements(
        f"python-dotenv==1.2.4 \\\n    --hash=sha256:{'0' * 64}\n", hashes
    )
    assert count == 1 and PURE in text


def test_cli_writes_output(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    manifest = tmp_path / "manifest.sha256"
    out = tmp_path / "out.txt"
    req.write_text(REQUIREMENTS)
    manifest.write_text(MANIFEST)
    result = subprocess.run(
        [
            "python3",
            str(REPO / "install/_wheelhouse_hashes.py"),
            str(req),
            str(manifest),
            str(out),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "2"
    assert NUMPY_PI in out.read_text()


def _run_wheelhouse_requirements(
    tmp_path: Path, manifest: str | None
) -> tuple[str, str]:
    wheel_dir = tmp_path / "wh" / "wheels"
    wheel_dir.mkdir(parents=True)
    req = tmp_path / "requirements.txt"
    req.write_text(REQUIREMENTS)
    manifest_path = tmp_path / "wh" / "manifest.sha256"
    if manifest is not None:
        manifest_path.write_text(manifest)
    script = f"""
set -euo pipefail
echo_success() {{ :; }}
echo_error() {{ :; }}
source "{REPO}/install/_common.sh"
SCRIPT_DIR="{REPO}/install"
WHEELHOUSE_DIR="{wheel_dir}"
WHEELHOUSE_MANIFEST="{manifest_path if manifest is not None else ''}"
wheelhouse_requirements "{req}"
"""
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )
    return result.stdout.strip(), str(req)


def test_shell_uses_extended_file_when_manifest_verified(tmp_path: Path) -> None:
    chosen, original = _run_wheelhouse_requirements(tmp_path, MANIFEST)
    assert chosen != original
    assert NUMPY_PI in Path(chosen).read_text()


def test_shell_keeps_original_without_manifest(tmp_path: Path) -> None:
    chosen, original = _run_wheelhouse_requirements(tmp_path, None)
    assert chosen == original


def test_manifest_only_exposed_after_verification() -> None:
    common = (REPO / "install/_common.sh").read_text()
    body = common[common.index("fetch_wheelhouse() {") :]
    body = body[: body.index("\n}\n")]
    verify = body.index('-c "$tmp_manifest"')
    expose = body.index('WHEELHOUSE_MANIFEST="$tmp_manifest"')
    assert verify < expose
    assert 'if [ "$have_manifest" = "1" ]' in body[verify : expose + 200]


@pytest.mark.parametrize("script", ["install.sh", "update.sh"])
def test_installers_use_wheelhouse_requirements(script: str) -> None:
    assert "wheelhouse_requirements" in (REPO / "install" / script).read_text()

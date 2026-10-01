"""Run the shared installer asset helper against actual temporary source files."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("missing_source", [False, True])
def test_install_asset_build_is_complete_or_fails(
    tmp_path: Path, missing_source: bool
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("build_css.py", "build_assets.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    styles = tmp_path / "src/static/styles"
    styles.mkdir(parents=True)
    (styles / "_imports.css").write_text("body { color: blue; }")
    sources = tmp_path / "src/static/scripts"
    sources.mkdir()
    shutil.copyfile(
        ROOT / "src/static/scripts/common_manifest.json",
        sources / "common_manifest.json",
    )
    for entry in json.loads((sources / "common_manifest.json").read_text()):
        name = entry["path"]
        (sources / name).write_text(
            f'window.probe_{Path(name).stem.replace("-", "_")} = true;'
        )
    if missing_source:
        (sources / "theme.js").unlink()
    installer = tmp_path / "install"
    installer.mkdir()
    shutil.copyfile(ROOT / "install/_common.sh", installer / "_common.sh")
    venv = tmp_path / "venv/bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(sys.executable)
    result = subprocess.run(
        [
            "bash",
            "-euc",
            'SCRIPT_DIR="$1"; VENV_PATH="$2"; source "$1/_common.sh"; build_css_bundle',
            "asset-test",
            str(installer),
            str(venv.parent),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    manifest = tmp_path / "src/static/dist/manifest.json"
    if missing_source:
        assert result.returncode != 0, result.stdout
        assert not manifest.exists()
        assert "Hashed JS/CSS asset build failed" in result.stdout + result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        mapping = json.loads(manifest.read_text())
        assert set(mapping) == {"common.js", "common.css"}
        assert all(
            (manifest.parent / name).stat().st_size > 0 for name in mapping.values()
        )

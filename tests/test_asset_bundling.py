"""Tests for JS/CSS asset bundling (JTN-287).

Covers:
- scripts/build_assets.py: manifest written, output files exist and non-empty.
- app_setup/asset_helpers.py: bundled_asset() returns correct filename.
- Graceful degradation when manifest is absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_assets.py"
SRC_ROOT = REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_build_assets(
    tmp_dist: Path, minify: bool = False
) -> subprocess.CompletedProcess:
    """Run build_assets.py with DIST_DIR redirected to *tmp_dist*.

    We monkey-patch the DIST_DIR and CSS_SOURCE inside the subprocess by
    importing the module and calling main() directly (avoids shell quoting
    and path issues on all platforms).
    """
    env_code = f"""
import sys, importlib
from pathlib import Path
sys.path.insert(0, str(Path(r"{REPO_ROOT}") / "scripts"))
sys.path.insert(0, str(Path(r"{SRC_ROOT}")))

import build_assets as ba

# Redirect output directory to tmp_path
ba.DIST_DIR = Path(r"{tmp_dist}")

# Redirect CSS source to the real main.css (built by build_css.py) or a stub.
real_css = Path(r"{SRC_ROOT}") / "static" / "styles" / "main.css"
if not real_css.is_file():
    # Create a tiny stub so the test can run without a full CSS build.
    stub_css = Path(r"{tmp_dist}") / "_stub_main.css"
    stub_css.parent.mkdir(parents=True, exist_ok=True)
    stub_css.write_text("body {{ margin: 0; }}", encoding="utf-8")
    ba.CSS_SOURCE = stub_css
else:
    ba.CSS_SOURCE = real_css

argv = {["--no-minify"] if not minify else []}
ba.main(argv)
"""
    return subprocess.run(
        [sys.executable, "-c", env_code],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Tests: build_assets.py
# ---------------------------------------------------------------------------


class TestBuildAssetsScript:
    def test_manifest_written(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        result = _run_build_assets(dist, minify=False)
        assert result.returncode == 0, f"build_assets failed:\n{result.stderr}"
        manifest_path = dist / "manifest.json"
        assert manifest_path.is_file(), "manifest.json was not written"

    def test_manifest_contains_required_keys(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        result = _run_build_assets(dist, minify=False)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((dist / "manifest.json").read_text())
        assert "common.js" in manifest, "manifest missing 'common.js'"
        assert "common.css" in manifest, "manifest missing 'common.css'"

    def test_js_bundle_exists_and_nonempty(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        result = _run_build_assets(dist, minify=False)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((dist / "manifest.json").read_text())
        js_file = dist / manifest["common.js"]
        assert js_file.is_file(), f"JS bundle file not found: {manifest['common.js']}"
        assert js_file.stat().st_size > 0, "JS bundle is empty"

    def test_css_bundle_exists_and_nonempty(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        result = _run_build_assets(dist, minify=False)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((dist / "manifest.json").read_text())
        css_file = dist / manifest["common.css"]
        assert (
            css_file.is_file()
        ), f"CSS bundle file not found: {manifest['common.css']}"
        assert css_file.stat().st_size > 0, "CSS bundle is empty"

    def test_js_bundle_contains_all_manifest_files(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        result = _run_build_assets(dist, minify=False)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((dist / "manifest.json").read_text())
        js_content = (dist / manifest["common.js"]).read_text(encoding="utf-8")
        # Each file in JS_MANIFEST should be referenced in the bundle
        for expected_file in ["theme.js", "csrf.js", "client_errors.js"]:
            assert (
                expected_file in js_content
            ), f"Expected '{expected_file}' marker in JS bundle"

    def test_hash_in_filename(self, tmp_path: Path) -> None:
        """Filenames must contain an 8-char hex hash for cache busting."""
        dist = tmp_path / "dist"
        result = _run_build_assets(dist, minify=False)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((dist / "manifest.json").read_text())
        for versioned in manifest.values():
            parts = versioned.split(".")
            # Expect: common.bundle.<hash>.[min.]js or .css
            hash_part = parts[2]
            assert (
                len(hash_part) == 8
            ), f"Expected 8-char hash in '{versioned}', got '{hash_part}'"
            assert all(
                c in "0123456789abcdef" for c in hash_part
            ), f"Hash '{hash_part}' is not hex"

    def test_deterministic_hash(self, tmp_path: Path) -> None:
        """Running twice with identical inputs should produce identical hashes."""
        dist1 = tmp_path / "dist1"
        dist2 = tmp_path / "dist2"
        _run_build_assets(dist1, minify=False)
        _run_build_assets(dist2, minify=False)
        m1 = json.loads((dist1 / "manifest.json").read_text())
        m2 = json.loads((dist2 / "manifest.json").read_text())
        assert m1 == m2, "Hashes differ between identical runs (non-deterministic)"


# ---------------------------------------------------------------------------
# Tests: asset_helpers.bundled_asset()
# ---------------------------------------------------------------------------


class TestBundledAssetHelper:
    def _make_manifest(self, tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def _get_helper(self, manifest_path: Path):
        """Import asset_helpers with the manifest path overridden."""
        import app_setup.asset_helpers as ah

        ah._override_manifest_path_for_tests(manifest_path)
        return ah

    def test_returns_versioned_filename(self, tmp_path: Path) -> None:
        manifest_path = self._make_manifest(
            tmp_path, {"common.js": "common.bundle.abc12345.min.js"}
        )
        ah = self._get_helper(manifest_path)
        assert ah.bundled_asset("common.js") == "common.bundle.abc12345.min.js"

    def test_returns_empty_string_for_missing_key(self, tmp_path: Path) -> None:
        manifest_path = self._make_manifest(tmp_path, {})
        ah = self._get_helper(manifest_path)
        assert ah.bundled_asset("nonexistent.js") == ""

    def test_graceful_degradation_no_manifest(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist" / "manifest.json"
        ah = self._get_helper(nonexistent)
        assert ah.bundled_asset("common.js") == ""

    def test_bundled_assets_enabled_true_when_manifest_present(
        self, tmp_path: Path
    ) -> None:
        manifest_path = self._make_manifest(
            tmp_path, {"common.js": "common.bundle.abc12345.min.js"}
        )
        ah = self._get_helper(manifest_path)
        # Simulate what setup_asset_helpers does
        manifest = ah._load_manifest()
        assert bool(manifest) is True

    def test_bundled_assets_enabled_false_when_no_manifest(
        self, tmp_path: Path
    ) -> None:
        nonexistent = tmp_path / "nope" / "manifest.json"
        ah = self._get_helper(nonexistent)
        manifest = ah._load_manifest()
        assert bool(manifest) is False


# ---------------------------------------------------------------------------
# Tests: Flask integration — setup_asset_helpers registers globals
# ---------------------------------------------------------------------------


class TestSetupAssetHelpers:
    def test_jinja_global_registered(self, tmp_path: Path, flask_app) -> None:
        """setup_asset_helpers must register 'bundled_asset' as a Jinja global."""
        import app_setup.asset_helpers as ah

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"common.js": "common.bundle.aabbccdd.min.js"}),
            encoding="utf-8",
        )
        ah._override_manifest_path_for_tests(manifest_path)
        ah.setup_asset_helpers(flask_app)

        assert "bundled_asset" in flask_app.jinja_env.globals
        assert callable(flask_app.jinja_env.globals["bundled_asset"])

    def test_bundled_assets_enabled_global(self, tmp_path: Path, flask_app) -> None:
        import app_setup.asset_helpers as ah

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"common.js": "common.bundle.aabbccdd.min.js"}),
            encoding="utf-8",
        )
        ah._override_manifest_path_for_tests(manifest_path)
        ah.setup_asset_helpers(flask_app)

        assert flask_app.jinja_env.globals["bundled_assets_enabled"] is True

    def test_bundled_assets_disabled_when_no_manifest(
        self, tmp_path: Path, flask_app
    ) -> None:
        import app_setup.asset_helpers as ah

        nonexistent = tmp_path / "nope" / "manifest.json"
        ah._override_manifest_path_for_tests(nonexistent)
        ah.setup_asset_helpers(flask_app)

        assert flask_app.jinja_env.globals["bundled_assets_enabled"] is False

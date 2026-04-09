"""Tests for Subresource Integrity helpers (JTN-478).

Covers:
- compute_sri: returns sha384- prefix, is deterministic, differs with different content
- sri_for: Jinja-friendly, cached, handles missing files gracefully
- cdn_sri: reads cdn_manifest.json, returns empty string for unknown keys
- init_sri: registers helpers as Jinja globals
- cdn_manifest.json: valid JSON with expected keys
- update_cdn_sri.py: computes correct hashes (uses responses/requests_mock)
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
CDN_MANIFEST_PATH = SRC_ROOT / "static" / "cdn_manifest.json"

# Make src importable
sys.path.insert(0, str(SRC_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sri(data: bytes) -> str:
    """Compute expected sha384-<base64> for *data*."""
    digest = hashlib.sha384(data).digest()
    return "sha384-" + base64.b64encode(digest).decode("ascii")


# ---------------------------------------------------------------------------
# Tests: compute_sri
# ---------------------------------------------------------------------------


class TestComputeSri:
    def test_returns_sha384_prefix(self, tmp_path: Path) -> None:
        f = tmp_path / "test.js"
        f.write_bytes(b"console.log('hello');")
        from utils.sri import compute_sri

        result = compute_sri(f)
        assert result.startswith("sha384-"), f"Expected sha384- prefix, got: {result}"

    def test_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "test.js"
        f.write_bytes(b"const x = 1;")
        from utils.sri import compute_sri

        assert compute_sri(f) == compute_sri(f)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.js"
        f2 = tmp_path / "b.js"
        f1.write_bytes(b"const a = 1;")
        f2.write_bytes(b"const b = 2;")
        from utils.sri import compute_sri

        assert compute_sri(f1) != compute_sri(f2)

    def test_hash_matches_expected(self, tmp_path: Path) -> None:
        data = b"hello world"
        f = tmp_path / "file.txt"
        f.write_bytes(data)
        from utils.sri import compute_sri

        expected = _make_sri(data)
        assert compute_sri(f) == expected

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        from utils.sri import compute_sri

        with pytest.raises(FileNotFoundError):
            compute_sri(tmp_path / "does_not_exist.js")


# ---------------------------------------------------------------------------
# Tests: sri_for (with cache reset between tests)
# ---------------------------------------------------------------------------


class TestSriFor:
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        from utils import sri as sri_mod

        sri_mod._reset_cache_for_tests()
        # Redirect static root to a temp dir for each test
        yield
        sri_mod._reset_cache_for_tests()

    def test_returns_sri_for_existing_file(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        data = b"htmx content"
        f = tmp_path / "htmx.min.js"
        f.write_bytes(data)
        expected = _make_sri(data)

        with patch.object(sri_mod, "_STATIC_ROOT", tmp_path):
            result = sri_mod.sri_for("htmx.min.js")

        assert result == expected

    def test_returns_empty_string_for_missing_file(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        with patch.object(sri_mod, "_STATIC_ROOT", tmp_path):
            result = sri_mod.sri_for("nonexistent.js")

        assert result == ""

    def test_missing_file_does_not_crash(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        # Should not raise
        with patch.object(sri_mod, "_STATIC_ROOT", tmp_path):
            sri_mod.sri_for("missing/path/file.js")

    def test_cached_same_result(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        data = b"cached content"
        f = tmp_path / "cached.js"
        f.write_bytes(data)

        with patch.object(sri_mod, "_STATIC_ROOT", tmp_path):
            first = sri_mod.sri_for("cached.js")
            second = sri_mod.sri_for("cached.js")

        assert first == second

    def test_caches_result_so_file_read_once(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        data = b"once only"
        f = tmp_path / "once.js"
        f.write_bytes(data)

        with patch.object(sri_mod, "_STATIC_ROOT", tmp_path):
            sri_mod.sri_for("once.js")
            # Remove the file — cache should still serve old value
            f.unlink()
            result = sri_mod.sri_for("once.js")

        assert result == _make_sri(data)

    def test_sri_for_real_htmx_vendored(self) -> None:
        """Sanity check: the actual vendored htmx.min.js produces a valid hash."""
        from utils import sri as sri_mod

        htmx_path = SRC_ROOT / "static" / "vendor" / "htmx.min.js"
        if not htmx_path.is_file():
            pytest.skip("htmx.min.js not present")

        result = sri_mod.sri_for("vendor/htmx.min.js")
        assert result.startswith("sha384-")
        assert len(result) > 20


# ---------------------------------------------------------------------------
# Tests: cdn_sri
# ---------------------------------------------------------------------------


class TestCdnSri:
    @pytest.fixture(autouse=True)
    def reset_cdn_cache(self):
        from utils import sri as sri_mod

        sri_mod._reset_cache_for_tests()
        yield
        sri_mod._reset_cache_for_tests()

    def test_returns_integrity_for_known_key(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        manifest = {
            "swagger-ui-bundle": {
                "url": "https://example.com/swagger.js",
                "integrity": "sha384-abc123",
            }
        }
        manifest_path = tmp_path / "cdn_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        sri_mod._override_cdn_manifest_path_for_tests(manifest_path)
        result = sri_mod.cdn_sri("swagger-ui-bundle")
        assert result == "sha384-abc123"

    def test_returns_empty_for_unknown_key(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        manifest = {}
        manifest_path = tmp_path / "cdn_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        sri_mod._override_cdn_manifest_path_for_tests(manifest_path)
        result = sri_mod.cdn_sri("nonexistent-key")
        assert result == ""

    def test_returns_empty_when_manifest_missing(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        sri_mod._override_cdn_manifest_path_for_tests(tmp_path / "does_not_exist.json")
        result = sri_mod.cdn_sri("any-key")
        assert result == ""

    def test_graceful_on_invalid_json(self, tmp_path: Path) -> None:
        from utils import sri as sri_mod

        bad_json = tmp_path / "cdn_manifest.json"
        bad_json.write_text("NOT JSON", encoding="utf-8")

        sri_mod._override_cdn_manifest_path_for_tests(bad_json)
        # Should not raise
        result = sri_mod.cdn_sri("any-key")
        assert result == ""


# ---------------------------------------------------------------------------
# Tests: init_sri registers Jinja globals
# ---------------------------------------------------------------------------


class TestInitSri:
    def test_jinja_globals_registered(self, flask_app) -> None:
        from utils.sri import init_sri

        init_sri(flask_app)
        assert "sri_for" in flask_app.jinja_env.globals
        assert "cdn_sri" in flask_app.jinja_env.globals
        assert callable(flask_app.jinja_env.globals["sri_for"])
        assert callable(flask_app.jinja_env.globals["cdn_sri"])

    def test_sri_for_renders_in_template(self, tmp_path: Path, flask_app) -> None:
        """sri_for should render a valid sha384- string in a Jinja template."""
        from utils import sri as sri_mod
        from utils.sri import init_sri

        data = b"var x = 1;"
        f = tmp_path / "test.js"
        f.write_bytes(data)
        expected = _make_sri(data)

        sri_mod._reset_cache_for_tests()
        with patch.object(sri_mod, "_STATIC_ROOT", tmp_path):
            init_sri(flask_app)
            with flask_app.app_context():
                rendered = flask_app.jinja_env.from_string(
                    "{{ sri_for('test.js') }}"
                ).render()

        assert rendered == expected

    def test_cdn_sri_renders_in_template(self, tmp_path: Path, flask_app) -> None:
        from utils import sri as sri_mod
        from utils.sri import init_sri

        manifest = {
            "my-lib": {
                "url": "https://example.com/lib.js",
                "integrity": "sha384-testvalue",
            }
        }
        manifest_path = tmp_path / "cdn_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        sri_mod._reset_cache_for_tests()
        sri_mod._override_cdn_manifest_path_for_tests(manifest_path)
        init_sri(flask_app)
        with flask_app.app_context():
            rendered = flask_app.jinja_env.from_string(
                "{{ cdn_sri('my-lib') }}"
            ).render()

        assert rendered == "sha384-testvalue"


# ---------------------------------------------------------------------------
# Tests: cdn_manifest.json validity
# ---------------------------------------------------------------------------


class TestCdnManifest:
    def test_manifest_is_valid_json(self) -> None:
        assert (
            CDN_MANIFEST_PATH.is_file()
        ), f"cdn_manifest.json not found at {CDN_MANIFEST_PATH}"
        manifest = json.loads(CDN_MANIFEST_PATH.read_text(encoding="utf-8"))
        assert isinstance(manifest, dict)

    def test_manifest_has_expected_keys(self) -> None:
        manifest = json.loads(CDN_MANIFEST_PATH.read_text(encoding="utf-8"))
        expected_keys = {"swagger-ui-css", "swagger-ui-bundle", "chart-js"}
        for key in expected_keys:
            assert key in manifest, f"cdn_manifest.json missing key: {key}"

    def test_manifest_entries_have_required_fields(self) -> None:
        manifest = json.loads(CDN_MANIFEST_PATH.read_text(encoding="utf-8"))
        for key, entry in manifest.items():
            assert "url" in entry, f"Entry '{key}' missing 'url'"
            assert "integrity" in entry, f"Entry '{key}' missing 'integrity'"
            assert entry["integrity"].startswith(
                "sha384-"
            ), f"Entry '{key}' integrity does not start with 'sha384-': {entry['integrity']}"


# ---------------------------------------------------------------------------
# Tests: update_cdn_sri.py script
# ---------------------------------------------------------------------------


class TestUpdateCdnSriScript:
    @pytest.fixture(autouse=True)
    def patch_sys_path(self):
        if str(SCRIPTS_ROOT) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_ROOT))
        yield

    def test_computes_correct_hash(self, tmp_path: Path) -> None:
        """update_cdn_sri should download and write correct hashes."""
        import update_cdn_sri as ucs

        fake_data = b"fake cdn content"
        expected_hash = _make_sri(fake_data)

        manifest = {
            "test-lib": {
                "url": "https://cdn.example.com/test.js",
                "version": "1.0.0",
                "integrity": "sha384-old",
            }
        }
        manifest_path = tmp_path / "cdn_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # Patch urllib.request.urlopen to return our fake data
        import unittest.mock as mock

        fake_response = mock.MagicMock()
        fake_response.read.return_value = fake_data
        fake_response.__enter__ = lambda s: s
        fake_response.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            exit_code = ucs.main(["--manifest", str(manifest_path)])

        assert exit_code == 0
        updated = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert updated["test-lib"]["integrity"] == expected_hash

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        """--dry-run should compute but not write."""
        import update_cdn_sri as ucs

        original_integrity = "sha384-original"
        manifest = {
            "test-lib": {
                "url": "https://cdn.example.com/test.js",
                "integrity": original_integrity,
            }
        }
        manifest_path = tmp_path / "cdn_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        import unittest.mock as mock

        fake_response = mock.MagicMock()
        fake_response.read.return_value = b"new content"
        fake_response.__enter__ = lambda s: s
        fake_response.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            exit_code = ucs.main(["--dry-run", "--manifest", str(manifest_path)])

        assert exit_code == 0
        # File should be unchanged
        still = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert still["test-lib"]["integrity"] == original_integrity

    def test_missing_manifest_returns_error(self, tmp_path: Path) -> None:
        import update_cdn_sri as ucs

        exit_code = ucs.main(["--manifest", str(tmp_path / "nope.json")])
        assert exit_code != 0

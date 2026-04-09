"""Contract tests: Content-Disposition headers on download/image endpoints (JTN-515).

Every route that sends file bytes must set an explicit Content-Disposition so
browsers cannot apply MIME-sniffing or silently render files inline.

Rules checked here:
  - download_logs  -> attachment; filename="inkypi_<timestamp>.log"
  - maybe_serve_webp PNG branch -> inline; filename="<name>.png"
  - maybe_serve_webp WebP branch -> inline; filename="<name>.png"
  - X-Content-Type-Options: nosniff set globally (spot-checked on download_logs)
"""

from __future__ import annotations

import os
import re
import sys

from PIL import Image

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SRC_ABS = os.path.join(PROJECT_ROOT, "src")
for _p in (PROJECT_ROOT, SRC_ABS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_inline(cd: str) -> None:
    """Assert Content-Disposition is inline with a properly quoted filename."""
    assert cd.startswith("inline;"), f"Expected inline disposition, got: {cd!r}"
    assert 'filename="' in cd, f"Filename not quoted in: {cd!r}"


def _assert_attachment(cd: str) -> None:
    """Assert Content-Disposition is attachment with a properly quoted filename."""
    assert cd.startswith("attachment;"), f"Expected attachment disposition, got: {cd!r}"
    assert 'filename="' in cd, f"Filename not quoted in: {cd!r}"


# ---------------------------------------------------------------------------
# download_logs — attachment disposition + quoted filename
# ---------------------------------------------------------------------------


class TestDownloadLogsHeaders:
    def test_attachment_disposition(self, client, monkeypatch):
        """download_logs must return attachment with a properly quoted filename."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "JOURNAL_AVAILABLE", False)
        resp = client.get("/download-logs")
        assert resp.status_code == 200
        cd = resp.headers.get("Content-Disposition", "")
        _assert_attachment(cd)

    def test_filename_matches_pattern(self, client, monkeypatch):
        """download_logs filename must match inkypi_YYYYMMDD-HHMMSS.log."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "JOURNAL_AVAILABLE", False)
        resp = client.get("/download-logs")
        assert resp.status_code == 200
        cd = resp.headers.get("Content-Disposition", "")
        assert re.search(
            r'filename="inkypi_\d{8}-\d{6}\.log"', cd
        ), f"Unexpected filename in: {cd!r}"

    def test_filename_has_safe_chars_only(self, client, monkeypatch):
        """Filename in Content-Disposition must contain only safe characters."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "JOURNAL_AVAILABLE", False)
        resp = client.get("/download-logs")
        assert resp.status_code == 200
        cd = resp.headers.get("Content-Disposition", "")
        m = re.search(r'filename="([^"]+)"', cd)
        assert m, f"No quoted filename found in: {cd!r}"
        fname = m.group(1)
        assert re.fullmatch(
            r"[a-zA-Z0-9._-]+", fname
        ), f"Filename contains unsafe characters: {fname!r}"

    def test_nosniff_header_present(self, client, monkeypatch):
        """download_logs response must include X-Content-Type-Options: nosniff."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "JOURNAL_AVAILABLE", False)
        resp = client.get("/download-logs")
        assert resp.status_code == 200
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


# ---------------------------------------------------------------------------
# maybe_serve_webp — inline disposition on both code paths
# ---------------------------------------------------------------------------


def _make_png(tmp_path, name="test.png"):
    p = tmp_path / name
    img = Image.new("RGB", (4, 4), color=(10, 20, 30))
    img.save(str(p), format="PNG")
    return p


class TestMaybeServeWebpHeaders:
    def test_png_path_sets_inline_disposition(self, tmp_path):
        """maybe_serve_webp PNG branch must set inline Content-Disposition."""
        from flask import Flask

        from utils.image_serving import maybe_serve_webp

        _make_png(tmp_path)
        app = Flask(__name__)
        with app.test_request_context("/"):
            resp = maybe_serve_webp(str(tmp_path), "test.png", accept_header=None)

        cd = resp.headers.get("Content-Disposition", "")
        _assert_inline(cd)
        assert "test.png" in cd, f"Filename missing from: {cd!r}"

    def test_webp_path_sets_inline_disposition(self, tmp_path):
        """maybe_serve_webp WebP branch must set inline Content-Disposition."""
        from flask import Flask

        from utils.image_serving import maybe_serve_webp

        _make_png(tmp_path)
        app = Flask(__name__)
        with app.test_request_context("/"):
            resp = maybe_serve_webp(
                str(tmp_path), "test.png", accept_header="image/webp"
            )

        cd = resp.headers.get("Content-Disposition", "")
        _assert_inline(cd)
        assert "test.png" in cd, f"Filename missing from: {cd!r}"

    def test_png_filename_quoted(self, tmp_path):
        """PNG branch filename must be double-quoted per RFC 6266."""
        from flask import Flask

        from utils.image_serving import maybe_serve_webp

        _make_png(tmp_path, "my-image.png")
        app = Flask(__name__)
        with app.test_request_context("/"):
            resp = maybe_serve_webp(str(tmp_path), "my-image.png", accept_header=None)

        cd = resp.headers.get("Content-Disposition", "")
        assert 'filename="my-image.png"' in cd, f"Expected quoted filename in: {cd!r}"

    def test_webp_filename_quoted(self, tmp_path):
        """WebP branch filename must be double-quoted per RFC 6266."""
        from flask import Flask

        from utils.image_serving import maybe_serve_webp

        _make_png(tmp_path, "my-image.png")
        app = Flask(__name__)
        with app.test_request_context("/"):
            resp = maybe_serve_webp(
                str(tmp_path), "my-image.png", accept_header="image/webp"
            )

        cd = resp.headers.get("Content-Disposition", "")
        assert 'filename="my-image.png"' in cd, f"Expected quoted filename in: {cd!r}"

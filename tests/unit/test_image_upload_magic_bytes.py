"""Tests for magic-bytes validation in handle_request_files / _validate_and_read_file.

JTN-514: Uploaded files must pass both a magic-byte check and PIL.verify()
before being accepted, regardless of the file extension supplied by the client.
"""

from __future__ import annotations

import os
from io import BytesIO

import pytest
from PIL import Image

import utils.app_utils as app_utils  # noqa: E402 (conftest adjusts sys.path)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeFile:
    """Minimal file-like object accepted by _validate_and_read_file."""

    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content
        self._pos = 0

        outer = self

        class _Stream:
            def seek(self, pos: int) -> None:
                outer._pos = pos

            def tell(self) -> int:
                return outer._pos

        self.stream = _Stream()

    def read(self) -> bytes:
        return self._content

    def seek(self, pos: int) -> None:
        self._pos = pos


class _FakeFiles:
    """Minimal multi-dict accepted by handle_request_files."""

    def __init__(self, pairs: list[tuple[str, _FakeFile]]) -> None:
        self._pairs = pairs

    def keys(self) -> list[str]:
        return [k for k, _ in self._pairs]

    def items(self, multi: bool = False) -> list[tuple[str, _FakeFile]]:
        return self._pairs


def _make_valid_png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _make_valid_jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), color=(0, 255, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def _make_valid_gif() -> bytes:
    buf = BytesIO()
    Image.new("P", (10, 10)).save(buf, format="GIF")
    return buf.getvalue()


def _make_valid_webp() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), color=(0, 0, 255)).save(buf, format="WEBP")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Direct unit tests for _validate_and_read_file
# ---------------------------------------------------------------------------


def test_valid_png_passes():
    """A genuine PNG is accepted and content is returned."""
    content = _make_valid_png()
    f = _FakeFile("photo.png", content)
    result_content, ext = app_utils._validate_and_read_file(f, "photo.png")
    assert ext == "png"
    assert result_content == content


def test_valid_jpeg_passes():
    """A genuine JPEG is accepted."""
    content = _make_valid_jpeg()
    f = _FakeFile("photo.jpg", content)
    result_content, ext = app_utils._validate_and_read_file(f, "photo.jpg")
    assert ext == "jpg"
    assert result_content == content


def test_valid_gif_passes():
    """A genuine GIF is accepted."""
    content = _make_valid_gif()
    f = _FakeFile("anim.gif", content)
    result_content, ext = app_utils._validate_and_read_file(f, "anim.gif")
    assert ext == "gif"
    assert result_content == content


def test_valid_webp_passes():
    """A genuine WebP is accepted."""
    content = _make_valid_webp()
    f = _FakeFile("img.webp", content)
    result_content, ext = app_utils._validate_and_read_file(f, "img.webp")
    assert ext == "webp"
    assert result_content == content


def test_text_file_renamed_to_png_rejected():
    """A plain-text file renamed to .png is rejected with RuntimeError."""
    content = b"Hello, world! This is definitely not an image."
    f = _FakeFile("evil.png", content)
    with pytest.raises(RuntimeError, match="not a valid image"):
        app_utils._validate_and_read_file(f, "evil.png")


def test_random_binary_renamed_to_png_rejected():
    """Random bytes with a .png extension are rejected."""
    content = os.urandom(512)
    f = _FakeFile("evil.png", content)
    with pytest.raises(RuntimeError, match="not a valid image"):
        app_utils._validate_and_read_file(f, "evil.png")


def test_empty_file_rejected():
    """An empty file is rejected regardless of extension."""
    f = _FakeFile("empty.png", b"")
    with pytest.raises(RuntimeError, match="not a valid image"):
        app_utils._validate_and_read_file(f, "empty.png")


def test_truncated_png_header_rejected():
    """Bytes that start with PNG magic but are not a valid PNG are rejected."""
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20  # valid magic, corrupt body
    f = _FakeFile("truncated.png", content)
    with pytest.raises(RuntimeError, match="not a valid image"):
        app_utils._validate_and_read_file(f, "truncated.png")


def test_jpeg_bytes_with_png_extension_rejected():
    """JPEG content uploaded as .png must be rejected (magic mismatch)."""
    content = _make_valid_jpeg()
    f = _FakeFile("photo.png", content)
    with pytest.raises(RuntimeError, match="not a valid image"):
        app_utils._validate_and_read_file(f, "photo.png")


def test_png_bytes_with_jpeg_extension_rejected():
    """PNG content uploaded as .jpg must be rejected (magic mismatch)."""
    content = _make_valid_png()
    f = _FakeFile("photo.jpg", content)
    with pytest.raises(RuntimeError, match="not a valid image"):
        app_utils._validate_and_read_file(f, "photo.jpg")


def test_exe_renamed_to_png_rejected():
    """A Windows PE executable renamed to .png is rejected."""
    # MZ header — the DOS stub of PE executables
    content = b"MZ" + b"\x90" * 510
    f = _FakeFile("malware.png", content)
    with pytest.raises(RuntimeError, match="not a valid image"):
        app_utils._validate_and_read_file(f, "malware.png")


# ---------------------------------------------------------------------------
# Integration via handle_request_files
# ---------------------------------------------------------------------------


def test_handle_request_files_accepts_valid_png(monkeypatch, tmp_path):
    """handle_request_files saves valid images and returns the file path."""
    monkeypatch.setattr(
        app_utils,
        "resolve_path",
        lambda p: str(tmp_path / os.path.basename(p)),
    )
    os.makedirs(str(tmp_path / "saved"), exist_ok=True)

    content = _make_valid_png()
    f = _FakeFile("photo.png", content)
    result = app_utils.handle_request_files(_FakeFiles([("imageFiles[]", f)]))
    assert "imageFiles[]" in result
    paths = result["imageFiles[]"]
    assert isinstance(paths, list)
    assert len(paths) == 1


def test_handle_request_files_rejects_bad_magic(monkeypatch, tmp_path):
    """handle_request_files propagates RuntimeError for files with bad magic."""
    monkeypatch.setattr(
        app_utils,
        "resolve_path",
        lambda p: str(tmp_path / os.path.basename(p)),
    )

    content = b"This is not an image at all."
    f = _FakeFile("evil.png", content)
    with pytest.raises(RuntimeError, match="not a valid image"):
        app_utils.handle_request_files(_FakeFiles([("imageFiles[]", f)]))


# ---------------------------------------------------------------------------
# _check_magic_bytes unit tests
# ---------------------------------------------------------------------------


def test_check_magic_bytes_png_valid():
    assert app_utils._check_magic_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "png")


def test_check_magic_bytes_png_invalid():
    assert not app_utils._check_magic_bytes(b"NOTPNG", "png")


def test_check_magic_bytes_jpeg_valid():
    assert app_utils._check_magic_bytes(b"\xff\xd8\xff" + b"\x00" * 20, "jpg")


def test_check_magic_bytes_gif87a_valid():
    assert app_utils._check_magic_bytes(b"GIF87a" + b"\x00" * 20, "gif")


def test_check_magic_bytes_gif89a_valid():
    assert app_utils._check_magic_bytes(b"GIF89a" + b"\x00" * 20, "gif")


def test_check_magic_bytes_webp_valid():
    content = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20
    assert app_utils._check_magic_bytes(content, "webp")


def test_check_magic_bytes_webp_invalid_brand():
    content = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI " + b"\x00" * 20
    assert not app_utils._check_magic_bytes(content, "webp")


def test_check_magic_bytes_heic_defers_to_pil():
    """HEIF/HEIC/AVIF have no simple prefix — magic check always returns True."""
    assert app_utils._check_magic_bytes(b"\x00" * 32, "heic")
    assert app_utils._check_magic_bytes(b"\x00" * 32, "heif")
    assert app_utils._check_magic_bytes(b"\x00" * 32, "avif")

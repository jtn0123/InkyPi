"""Validate metadata against actual compressed bytes and release identity."""

import hashlib
import lzma
from pathlib import Path

import pytest
from scripts.pi_image_manifest import build_manifest


def test_manifest_describes_actual_image(tmp_path: Path) -> None:
    source = b"real decompressed image bytes" * 100
    image = tmp_path / "inkypi-1.4.3-pi-zero-2-w.img.xz"
    image.write_bytes(lzma.compress(source))
    entry = build_manifest(image, "v1.4.3")["os_list"]
    assert isinstance(entry, list)
    item = entry[0]
    assert item["init_format"] == "systemd"
    assert item["devices"] == ["pi2-zero"]
    assert set(item) >= {
        "name",
        "description",
        "icon",
        "url",
        "extract_size",
        "extract_sha256",
        "image_download_size",
        "release_date",
        "devices",
    }
    assert item["extract_sha256"] == hashlib.sha256(source).hexdigest()
    assert item["extract_size"] == len(source)
    assert item["image_download_size"] == image.stat().st_size
    assert item["url"].endswith(f"/v1.4.3/{image.name}")


@pytest.mark.parametrize("tag", ["v1.4.4", "v1.4.3/evil", "1.4.3"])
def test_manifest_rejects_mismatched_or_invalid_tag(tmp_path: Path, tag: str) -> None:
    with pytest.raises(ValueError):
        build_manifest(tmp_path / "inkypi-1.4.3-pi-zero-2-w.img.xz", tag)

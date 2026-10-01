"""Produce Raspberry Pi Imager metadata for the pinned Bookworm image."""

import argparse
import hashlib
import json
import lzma
import re
from pathlib import Path


def build_manifest(image: Path, tag: str) -> dict[str, object]:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", tag):
        raise ValueError("Invalid release tag")
    expected = f"inkypi-{tag[1:]}-pi-zero-2-w.img.xz"
    if image.name != expected:
        raise ValueError("Image filename does not match the release tag")
    digest = hashlib.sha256()
    size = 0
    with lzma.open(image, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {
        "os_list": [
            {
                "name": f"InkyPi {tag} (Pi Zero 2 W)",
                "description": "Pre-installed InkyPi on Raspberry Pi OS Lite Bookworm arm64",
                "url": f"https://github.com/jtn0123/InkyPi/releases/download/{tag}/{expected}",
                "website": "https://github.com/jtn0123/InkyPi",
                "init_format": "systemd",
                "image_download_size": image.stat().st_size,
                "extract_size": size,
                "extract_sha256": digest.hexdigest(),
            }
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(build_manifest(args.image, args.tag), indent=2) + "\n"
    )


if __name__ == "__main__":
    main()

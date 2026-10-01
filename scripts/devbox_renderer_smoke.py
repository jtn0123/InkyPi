"""Render through the actual Devbox Chromium subprocess, without pytest mocks."""

import tempfile
from pathlib import Path

from utils.image_utils import take_screenshot


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "smoke.html"
        source.write_text(
            '<html><body style="margin:0;background:rgb(20,80,140)">'
            '<h1 style="color:white">InkyPi Chromium smoke</h1></body></html>'
        )
        image = take_screenshot(source.as_uri(), (320, 200))
        assert image is not None, "Chromium did not produce an image"
        assert image.size == (320, 200), image.size
        assert image.convert("RGB").getpixel((310, 190)) == (20, 80, 140)
        assert len(image.convert("RGB").getcolors(64000) or []) > 1
        destination = Path(".Codex/devbox-render.png")
        destination.parent.mkdir(exist_ok=True)
        image.save(destination)
        print(f"Actual Chromium render verified: {destination}")


if __name__ == "__main__":
    main()

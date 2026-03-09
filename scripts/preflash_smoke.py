#!/usr/bin/env python3

import argparse
import os
import sys
import tempfile
from pathlib import Path


def _prepare_env(runtime_dir: str) -> None:
    os.environ["INKYPI_ENV"] = "dev"
    os.environ["INKYPI_NO_REFRESH"] = "1"
    os.environ["INKYPI_RUNTIME_DIR"] = runtime_dir


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _src_path() -> Path:
    return _repo_root() / "src"


def _ensure_src_on_path() -> None:
    src = str(_src_path())
    if src not in sys.path:
        sys.path.insert(0, src)


def run_app_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflash-app-") as tmpdir:
        _prepare_env(tmpdir)
        _ensure_src_on_path()

        import inkypi

        inkypi.main(["--dev", "--web-only", "--port", "8099"])
        app = inkypi.app
        if app is None:
            raise RuntimeError("Flask app was not initialized")

        client = app.test_client()
        response = client.get("/healthz")
        if response.status_code != 200:
            raise RuntimeError(f"/healthz returned {response.status_code}")

        device_config = app.config["DEVICE_CONFIG"]
        if device_config.get_config("display_type") != "mock":
            raise RuntimeError("Dev config did not resolve to mock display")

        if not Path(device_config.processed_image_file).exists():
            raise RuntimeError("Processed preview image was not created")


def run_render_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflash-render-") as tmpdir:
        _prepare_env(tmpdir)
        _ensure_src_on_path()

        from PIL import Image
        from config import Config
        from display.display_manager import DisplayManager

        device_config = Config()
        display_manager = DisplayManager(device_config)
        image = Image.new("RGB", (320, 240), "white")
        display_manager.display_image(image)

        current_image = Path(device_config.current_image_file)
        processed_image = Path(device_config.processed_image_file)
        mock_output = Path(tmpdir) / "mock_display_output" / "latest.png"

        missing = [
            str(path)
            for path in (current_image, processed_image, mock_output)
            if not path.exists()
        ]
        if missing:
            raise RuntimeError(f"Expected render artifacts missing: {', '.join(missing)}")


def run_import_smoke() -> None:
    import flask  # noqa: F401
    import PIL  # noqa: F401
    import waitress  # noqa: F401
    from inky.auto import auto  # noqa: F401


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-flash smoke checks")
    parser.add_argument(
        "mode",
        choices=("app", "render", "imports"),
        help="Smoke check to run",
    )
    args = parser.parse_args()

    if args.mode == "app":
        run_app_smoke()
    elif args.mode == "render":
        run_render_smoke()
    else:
        run_import_smoke()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

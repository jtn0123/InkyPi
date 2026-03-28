#!/usr/bin/env python3

import argparse
import gc
import importlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _src_path() -> Path:
    return _repo_root() / "src"


def _ensure_src_on_path() -> None:
    src = str(_src_path())
    if src not in sys.path:
        sys.path.insert(0, src)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _prepare_env(runtime_dir: str, config_path: str | None = None, web_only: bool = True) -> None:
    os.environ["INKYPI_ENV"] = "dev"
    os.environ["INKYPI_RUNTIME_DIR"] = runtime_dir
    if web_only:
        os.environ["INKYPI_NO_REFRESH"] = "1"
    else:
        os.environ.pop("INKYPI_NO_REFRESH", None)
    if config_path:
        os.environ["INKYPI_CONFIG_FILE"] = config_path
    else:
        os.environ.pop("INKYPI_CONFIG_FILE", None)


def _base_config(runtime_dir: str) -> dict:
    return {
        "name": "InkyPi Preflight",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "timezone": "UTC",
        "time_format": "24h",
        "plugin_cycle_interval_seconds": 300,
        "startup": False,
        "output_dir": str(Path(runtime_dir) / "mock_display_output"),
        "enable_benchmarks": False,
        "benchmark_sample_rate": 1.0,
        "benchmarks_db_path": str(Path(runtime_dir) / "benchmarks.db"),
        "image_settings": {
            "saturation": 1.0,
            "brightness": 1.0,
            "sharpness": 1.0,
            "contrast": 1.0,
        },
        "playlist_config": {
            "playlists": [
                {
                    "name": "Default",
                    "start_time": "00:00",
                    "end_time": "24:00",
                    "plugins": [],
                    "current_plugin_index": None,
                }
            ],
            "active_playlist": None,
        },
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": None,
            "plugin_id": None,
        },
    }


def _write_config(runtime_dir: str, overrides: dict | None = None) -> str:
    payload = _base_config(runtime_dir)
    payload.update(overrides or {})
    config_path = Path(runtime_dir) / "device.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return str(config_path)


def _load_inkypi(runtime_dir: str, config_path: str | None = None, web_only: bool = True):
    _prepare_env(runtime_dir, config_path=config_path, web_only=web_only)
    _ensure_src_on_path()
    sys.modules.pop("inkypi", None)
    inkypi = importlib.import_module("inkypi")
    inkypi = importlib.reload(inkypi)
    argv = ["--dev", "--port", "8099"]
    if web_only:
        argv.append("--web-only")
    inkypi.main(argv)
    app = inkypi.app
    if app is None:
        raise RuntimeError("Flask app was not initialized")
    return inkypi, app


def _probe_routes(client, routes: list[str]) -> None:
    for route in routes:
        response = client.get(route)
        if response.status_code != 200:
            raise RuntimeError(f"{route} returned {response.status_code}")


def _force_inprocess_execution(refresh_task=None) -> None:
    """Disable subprocess isolation so plugins run in the current process.

    This avoids pickling issues with the ``spawn``/``forkserver``
    multiprocessing start methods on Linux CI and keeps monkey-patches
    visible to the plugin code.
    """
    os.environ["INKYPI_PLUGIN_ISOLATION"] = "none"
    # Prevent dev-mode hot-reload from wiping monkey-patches on plugin modules.
    os.environ["INKYPI_NO_HOT_RELOAD"] = "1"


def run_app_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflash-app-") as tmpdir:
        _ensure_src_on_path()
        _, app = _load_inkypi(tmpdir, web_only=True)
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
    import astral  # noqa: F401
    import feedparser  # noqa: F401
    import flask  # noqa: F401
    import icalendar  # noqa: F401
    import jsonschema  # noqa: F401
    import numpy  # noqa: F401
    import openai  # noqa: F401
    import pi_heif  # noqa: F401
    import PIL  # noqa: F401
    import psutil  # noqa: F401
    import pytz  # noqa: F401
    import recurring_ical_events  # noqa: F401
    import requests  # noqa: F401
    import urllib3  # noqa: F401
    import waitress  # noqa: F401

    if platform.system() == "Linux":
        from cysystemd.daemon import notify  # noqa: F401
        from inky.auto import auto  # noqa: F401


def run_pi_runtime_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflight-pi-runtime-") as tmpdir:
        config_path = _write_config(tmpdir)
        _, app = _load_inkypi(tmpdir, config_path=config_path, web_only=True)
        client = app.test_client()
        _probe_routes(
            client,
            [
                "/",
                "/settings",
                "/playlist",
                "/healthz",
                "/api/health/system",
                "/api/health/plugins",
                "/preview",
            ],
        )
        device_config = app.config["DEVICE_CONFIG"]
        if not Path(device_config.processed_image_file).exists():
            raise RuntimeError("Processed preview image missing after runtime smoke")


def run_cold_boot_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflight-cold-boot-") as tmpdir:
        config_path = _write_config(
            tmpdir,
            overrides={
                "startup": True,
                "enable_benchmarks": True,
            },
        )
        _ensure_src_on_path()
        inkypi, app = _load_inkypi(tmpdir, config_path=config_path, web_only=False)
        device_config = app.config["DEVICE_CONFIG"]
        display_manager = app.config["DISPLAY_MANAGER"]
        refresh_task = app.config["REFRESH_TASK"]
        _force_inprocess_execution(refresh_task)

        refresh_task.start()
        try:
            if device_config.get_config("startup") is True:
                img = inkypi.generate_startup_image(device_config.get_resolution())
                display_manager.display_image(img)
                device_config.update_value("startup", False, write=True)

            from refresh_task import ManualRefresh

            refresh_task.manual_update(ManualRefresh("clock", {}))
        finally:
            refresh_task.stop()

        history_dir = Path(device_config.history_image_dir)
        if not Path(device_config.current_image_file).exists():
            raise RuntimeError("Current image missing after cold boot smoke")
        if not Path(device_config.processed_image_file).exists():
            raise RuntimeError("Processed image missing after cold boot smoke")
        if not list(history_dir.glob("display_*.png")):
            raise RuntimeError("History PNG missing after cold boot smoke")
        if not list(history_dir.glob("display_*.json")):
            raise RuntimeError("History metadata missing after cold boot smoke")
        refresh_info = device_config.get_refresh_info()
        if refresh_info.plugin_id != "clock":
            raise RuntimeError("Refresh info was not updated for first refresh")
        if device_config.get_config("startup") is not False:
            raise RuntimeError("Startup flag was not cleared")


def run_cache_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflight-cache-") as tmpdir:
        config_path = _write_config(tmpdir)
        _prepare_env(tmpdir, config_path=config_path, web_only=True)
        _ensure_src_on_path()

        from PIL import Image

        import plugins.ai_text.ai_text as ai_text_mod
        from config import Config
        from display.display_manager import DisplayManager
        from refresh_task import ManualRefresh, RefreshTask

        device_config = Config()
        display_manager = DisplayManager(device_config)
        refresh_task = RefreshTask(device_config, display_manager)
        _force_inprocess_execution(refresh_task)

        writes = {"count": 0}

        def fake_display(img, image_settings=None):
            writes["count"] += 1

        display_manager.display.display_image = fake_display

        calls = {"count": 0}

        def fake_generate(self, settings, cfg):
            calls["count"] += 1
            return Image.new("RGB", cfg.get_resolution(), (200, 200, 200))

        original_generate = ai_text_mod.AIText.generate_image
        ai_text_mod.AIText.generate_image = fake_generate

        refresh_task.start()
        try:
            settings = {"title": "T", "textModel": "gpt-4o", "textPrompt": "Hi"}
            metrics1 = refresh_task.manual_update(ManualRefresh("ai_text", settings))
            metrics2 = refresh_task.manual_update(ManualRefresh("ai_text", settings))
        finally:
            refresh_task.stop()
            ai_text_mod.AIText.generate_image = original_generate

        if writes["count"] != 1:
            raise RuntimeError(f"Expected 1 display write, saw {writes['count']}")
        if metrics1 is None or metrics1.get("display_ms") is None:
            raise RuntimeError("Initial refresh did not record display metrics")
        if metrics2 is None or metrics2.get("display_ms") is not None:
            raise RuntimeError("Cached refresh unexpectedly recorded display work")
        if device_config.get_refresh_info().used_cached is not True:
            raise RuntimeError("Refresh info did not record used_cached=True")


def _query_single_value(db_path: Path, query: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(query).fetchone()
    return int(row[0] or 0)


def run_benchmark_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflight-bench-") as tmpdir:
        config_path = _write_config(
            tmpdir,
            overrides={
                "enable_benchmarks": True,
                "benchmark_sample_rate": 1.0,
            },
        )
        _prepare_env(tmpdir, config_path=config_path, web_only=True)
        _ensure_src_on_path()

        from PIL import Image

        import plugins.ai_text.ai_text as ai_text_mod
        from config import Config
        from display.display_manager import DisplayManager
        from refresh_task import ManualRefresh, RefreshTask

        device_config = Config()
        device_config.update_value("enable_benchmarks", True)
        db_path = Path(device_config.get_config("benchmarks_db_path"))
        display_manager = DisplayManager(device_config)
        refresh_task = RefreshTask(device_config, display_manager)
        _force_inprocess_execution(refresh_task)

        calls = {"count": 0}

        def fake_generate(self, settings, cfg):
            calls["count"] += 1
            color = (calls["count"] * 40) % 255
            return Image.new("RGB", cfg.get_resolution(), (color, 100, 150))

        ai_text_mod.AIText.generate_image = fake_generate

        refresh_task.start()
        try:
            settings = {"title": "T", "textModel": "gpt-4o", "textPrompt": "Hi"}
            for _ in range(5):
                refresh_task.manual_update(ManualRefresh("ai_text", settings))
        finally:
            refresh_task.stop()

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT request_ms, generate_ms, preprocess_ms, display_ms
                FROM refresh_events
                WHERE plugin_id = 'ai_text'
                ORDER BY id
                """
            ).fetchall()
        if len(rows) < 5:
            raise RuntimeError("Benchmark smoke did not record enough refresh rows")

        request_vals = [int(row[0]) for row in rows if row[0] is not None]
        generate_vals = [int(row[1]) for row in rows if row[1] is not None]
        preprocess_vals = [int(row[2]) for row in rows if row[2] is not None]
        display_vals = [int(row[3]) for row in rows if row[3] is not None]
        if not preprocess_vals or not display_vals:
            raise RuntimeError("Benchmark smoke missing preprocess/display metrics")

        if max(request_vals) > 10000:
            raise RuntimeError(f"request_ms threshold exceeded: {max(request_vals)}")
        if max(generate_vals) > 8000:
            raise RuntimeError(f"generate_ms threshold exceeded: {max(generate_vals)}")
        if max(preprocess_vals) > 5000:
            raise RuntimeError(f"preprocess_ms threshold exceeded: {max(preprocess_vals)}")
        if max(display_vals) > 5000:
            raise RuntimeError(f"display_ms threshold exceeded: {max(display_vals)}")

        generate_stage_rows = _query_single_value(
            db_path,
            "SELECT COUNT(*) FROM stage_events WHERE stage = 'generate_image'",
        )
        display_stage_rows = _query_single_value(
            db_path,
            "SELECT COUNT(*) FROM stage_events WHERE stage = 'display_pipeline'",
        )
        driver_stage_rows = _query_single_value(
            db_path,
            "SELECT COUNT(*) FROM stage_events WHERE stage = 'display_driver'",
        )
        if generate_stage_rows < 5:
            raise RuntimeError("Benchmark smoke missing generate_image stage events")
        if display_stage_rows < 1:
            raise RuntimeError("Benchmark smoke missing display pipeline stage events")
        if driver_stage_rows < 1:
            raise RuntimeError("Benchmark smoke missing display driver stage events")


def run_browser_render_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflight-browser-") as tmpdir:
        _prepare_env(tmpdir)
        _ensure_src_on_path()
        from utils.image_utils import take_screenshot_html

        html = "<html><body><div style='width:100%;height:100%;background:#fff'>InkyPi</div></body></html>"
        image = take_screenshot_html(html, (320, 240), timeout_ms=10000)
        if image is None:
            raise RuntimeError("Browser render smoke did not produce an image")
        if image.size != (320, 240):
            raise RuntimeError(f"Browser render returned wrong size: {image.size}")


def _run_bash(command: str) -> None:
    subprocess.run(["bash", "-lc", command], check=True, capture_output=True, text=True)


def run_install_idempotency_smoke() -> None:
    if platform.system() != "Linux":
        raise RuntimeError("Install idempotency smoke is Linux-only")

    with tempfile.TemporaryDirectory(prefix="inkypi-install-idem-") as tmpdir:
        temp = Path(tmpdir)
        config_txt = temp / "config.txt"
        config_txt.write_text("dtparam=spi=on\n", encoding="utf-8")
        for overlay in ("dtoverlay=spi0-0cs", "dtoverlay=spi0-2cs"):
            work = temp / f"{overlay.replace('=', '_')}.txt"
            work.write_text(config_txt.read_text(encoding="utf-8"), encoding="utf-8")
            command = (
                f"if ! grep -E -q '^[[:space:]]*{overlay}' '{work}'; then "
                f"sed -i '/^dtparam=spi=on/a {overlay}' '{work}'; fi; "
                f"if ! grep -E -q '^[[:space:]]*{overlay}' '{work}'; then "
                f"sed -i '/^dtparam=spi=on/a {overlay}' '{work}'; fi"
            )
            _run_bash(command)
            lines = work.read_text(encoding="utf-8").splitlines()
            if lines.count(overlay) != 1:
                raise RuntimeError(f"Overlay duplication detected for {overlay}")

        template = temp / "template.json"
        template.write_text('{"name":"Template","startup":true}', encoding="utf-8")
        device_json = temp / "device.json"
        bootstrap = (
            f"if [ ! -f '{device_json}' ]; then cp '{template}' '{device_json}'; fi; "
            f"if [ ! -f '{device_json}' ]; then cp '{template}' '{device_json}'; fi"
        )
        _run_bash(bootstrap)
        initial = device_json.read_text(encoding="utf-8")
        device_json.write_text('{"name":"Existing","startup":false}', encoding="utf-8")
        _run_bash(bootstrap)
        if device_json.read_text(encoding="utf-8") != '{"name":"Existing","startup":false}':
            raise RuntimeError("Bootstrap logic overwrote existing device.json")
        if "Template" not in initial:
            raise RuntimeError("Bootstrap logic failed to create initial device.json")

        ws_config = temp / "waveshare.json"
        ws_config.write_text('{"display_type": "inky"}', encoding="utf-8")
        update_display = (
            f"sed -i 's/\\\"display_type\\\": \\\".*\\\"/\\\"display_type\\\": \\\"epd7in3f\\\"/' '{ws_config}'; "
            f"sed -i 's/\\\"display_type\\\": \\\".*\\\"/\\\"display_type\\\": \\\"epd7in3f\\\"/' '{ws_config}'"
        )
        _run_bash(update_display)
        if ws_config.read_text(encoding="utf-8").count('"display_type": "epd7in3f"') != 1:
            raise RuntimeError("Waveshare display_type update was not idempotent")


def run_soak_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="inkypi-preflight-soak-") as tmpdir:
        config_path = _write_config(
            tmpdir,
            overrides={
                "enable_benchmarks": True,
                "benchmark_sample_rate": 1.0,
            },
        )
        _prepare_env(tmpdir, config_path=config_path, web_only=True)
        _ensure_src_on_path()

        import psutil
        from PIL import Image

        from config import Config
        from display.display_manager import DisplayManager
        from refresh_task import ManualRefresh, RefreshTask

        class SoakPlugin:
            config = {"image_settings": []}

            def __init__(self):
                self.calls = 0

            def generate_image(self, settings, device_config):
                self.calls += 1
                color = (self.calls * 17) % 255
                return Image.new("RGB", device_config.get_resolution(), (color, 120, 200))

        device_config = Config()
        display_manager = DisplayManager(device_config)
        refresh_task = RefreshTask(device_config, display_manager)
        _force_inprocess_execution(refresh_task)

        import refresh_task as refresh_task_mod

        plugin = SoakPlugin()
        original_get_plugin_instance = refresh_task_mod.get_plugin_instance
        original_get_plugin = device_config.get_plugin

        refresh_task_mod.get_plugin_instance = lambda cfg: plugin
        device_config.get_plugin = lambda plugin_id: {"id": plugin_id, "class": "Soak"}
        process = psutil.Process(os.getpid())
        baseline_rss = process.memory_info().rss
        db_path = Path(device_config.get_config("benchmarks_db_path"))

        refresh_task.start()
        try:
            for _ in range(30):
                refresh_task.manual_update(ManualRefresh("soak", {}))
        finally:
            refresh_task.stop()
            refresh_task_mod.get_plugin_instance = original_get_plugin_instance
            device_config.get_plugin = original_get_plugin

        gc.collect()
        final_rss = process.memory_info().rss
        rss_growth_mb = (final_rss - baseline_rss) / 1024 / 1024
        if rss_growth_mb > 50:
            raise RuntimeError(f"Soak smoke memory growth too high: {rss_growth_mb:.2f}MB")
        if refresh_task.manual_update_requests:
            raise RuntimeError("Soak smoke left queued manual updates behind")
        refresh_rows = _query_single_value(
            db_path,
            "SELECT COUNT(*) FROM refresh_events WHERE plugin_id = 'soak'",
        )
        if refresh_rows < 30:
            raise RuntimeError("Soak smoke did not persist enough benchmark rows")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-flash smoke checks")
    parser.add_argument(
        "mode",
        choices=(
            "app",
            "render",
            "imports",
            "pi-runtime",
            "cold-boot",
            "cache",
            "benchmarks",
            "browser-render",
            "install-idempotency",
            "soak",
        ),
        help="Smoke check to run",
    )
    args = parser.parse_args()

    if args.mode == "app":
        run_app_smoke()
    elif args.mode == "render":
        run_render_smoke()
    elif args.mode == "imports":
        run_import_smoke()
    elif args.mode == "pi-runtime":
        run_pi_runtime_smoke()
    elif args.mode == "cold-boot":
        run_cold_boot_smoke()
    elif args.mode == "cache":
        run_cache_smoke()
    elif args.mode == "benchmarks":
        run_benchmark_smoke()
    elif args.mode == "browser-render":
        run_browser_render_smoke()
    elif args.mode == "soak":
        run_soak_smoke()
    else:
        run_install_idempotency_smoke()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# pyright: reportMissingImports=false
"""Tests for scripts/dry_run_plugin.py — the offline plugin dry-run CLI."""

import importlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from PIL import Image

# ── helpers ─────────────────────────────────────────────────────────────────


def _import_dry_run() -> Any:
    """Import the dry_run_plugin script as a module (adds src/ to sys.path)."""
    repo_root = Path(__file__).parent.parent
    script_path = repo_root / "scripts" / "dry_run_plugin.py"
    spec = importlib.util.spec_from_file_location("dry_run_plugin", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def dry_run_mod() -> Any:
    """Session-scoped import of dry_run_plugin to share across tests."""
    return _import_dry_run()


# ── unit: _MockDeviceConfig ──────────────────────────────────────────────────


def test_mock_device_config_get_resolution(dry_run_mod: Any) -> None:
    cfg = dry_run_mod._MockDeviceConfig(1200, 600, "horizontal", "UTC")
    assert cfg.get_resolution() == (1200, 600)


def test_mock_device_config_orientation(dry_run_mod: Any) -> None:
    cfg = dry_run_mod._MockDeviceConfig(800, 480, "vertical", "UTC")
    assert cfg.get_config("orientation") == "vertical"


def test_mock_device_config_timezone(dry_run_mod: Any) -> None:
    cfg = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "Europe/London")
    assert cfg.get_config("timezone") == "Europe/London"


def test_mock_device_config_missing_key_returns_default(dry_run_mod: Any) -> None:
    cfg = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "UTC")
    assert cfg.get_config("does_not_exist", default="fallback") == "fallback"
    assert cfg.get_config("does_not_exist") is None


def test_mock_device_config_load_env_key(
    dry_run_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_TEST_KEY", "secret_value")
    cfg = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "UTC")
    assert cfg.load_env_key("MY_TEST_KEY") == "secret_value"


# ── unit: _discover_plugin_config ────────────────────────────────────────────


def test_discover_plugin_config_year_progress(dry_run_mod: Any) -> None:
    cfg = dry_run_mod._discover_plugin_config("year_progress")
    assert cfg["id"] == "year_progress"
    assert cfg["class"] == "YearProgress"


def test_discover_plugin_config_missing_plugin_exits(dry_run_mod: Any) -> None:
    with pytest.raises(SystemExit):
        dry_run_mod._discover_plugin_config("plugin_does_not_exist_xyz")


# ── unit: _load_settings ─────────────────────────────────────────────────────


def test_load_settings_no_config(dry_run_mod: Any) -> None:
    assert dry_run_mod._load_settings(None) == {}


def test_load_settings_valid_json(dry_run_mod: Any, tmp_path: Path) -> None:
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps({"selectedFrame": "None", "style": "dark"}))
    result = dry_run_mod._load_settings(str(cfg_file))
    assert result == {"selectedFrame": "None", "style": "dark"}


def test_load_settings_missing_file_exits(dry_run_mod: Any, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        dry_run_mod._load_settings(str(tmp_path / "nonexistent.json"))


def test_load_settings_non_object_exits(dry_run_mod: Any, tmp_path: Path) -> None:
    cfg_file = tmp_path / "bad.json"
    cfg_file.write_text(json.dumps(["a", "b", "c"]))
    with pytest.raises(SystemExit):
        dry_run_mod._load_settings(str(cfg_file))


# ── integration: year_progress generates a PNG ───────────────────────────────


def test_year_progress_produces_png(dry_run_mod: Any, tmp_path: Path) -> None:
    """Run generate_image() via the dry-run helpers and verify a PNG is created."""
    from plugins.plugin_registry import get_plugin_instance, load_plugins

    plugin_config = dry_run_mod._discover_plugin_config("year_progress")
    load_plugins([plugin_config])

    device_config = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "UTC")
    plugin_instance = get_plugin_instance(plugin_config)
    image = plugin_instance.generate_image({}, device_config)

    output = tmp_path / "out.png"
    image.save(str(output))

    assert output.exists(), "PNG was not saved"
    loaded = Image.open(output)
    assert loaded.width == 800
    assert loaded.height == 480


def test_year_progress_custom_dimensions(dry_run_mod: Any, tmp_path: Path) -> None:
    """Verify that the mock device config's resolution flows through to the image."""
    from plugins.plugin_registry import get_plugin_instance, load_plugins

    plugin_config = dry_run_mod._discover_plugin_config("year_progress")
    load_plugins([plugin_config])

    device_config = dry_run_mod._MockDeviceConfig(640, 400, "horizontal", "UTC")
    plugin_instance = get_plugin_instance(plugin_config)
    image = plugin_instance.generate_image({}, device_config)

    output = tmp_path / "out_640.png"
    image.save(str(output))

    assert output.exists()
    loaded = Image.open(output)
    assert loaded.width == 640
    assert loaded.height == 400


def test_year_progress_config_override(dry_run_mod: Any, tmp_path: Path) -> None:
    """--config JSON override is loaded and passed as settings to generate_image()."""
    from plugins.plugin_registry import get_plugin_instance, load_plugins

    # Write a settings file that year_progress will silently accept (unknown keys are ok)
    settings = {"selectedFrame": "None", "custom_option": "value"}
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps(settings))

    loaded_settings = dry_run_mod._load_settings(str(cfg_file))
    assert loaded_settings == settings

    plugin_config = dry_run_mod._discover_plugin_config("year_progress")
    load_plugins([plugin_config])

    device_config = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "UTC")
    plugin_instance = get_plugin_instance(plugin_config)

    # generate_image must succeed even with extra/unknown settings keys
    image = plugin_instance.generate_image(loaded_settings, device_config)
    assert isinstance(image, Image.Image)


# ── integration: main() end-to-end via argv patching ─────────────────────────


def test_main_writes_png_for_year_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Call main() directly with year_progress and verify the PNG is created."""
    output = tmp_path / "result.png"
    test_argv = [
        "dry_run_plugin.py",
        "--plugin",
        "year_progress",
        "--output",
        str(output),
        "--width",
        "800",
        "--height",
        "480",
        "--timezone",
        "UTC",
    ]
    with patch.object(sys, "argv", test_argv):
        mod = _import_dry_run()
        mod.main()

    assert output.exists(), f"Expected PNG at {output}"
    img = Image.open(output)
    assert img.width == 800
    assert img.height == 480


def test_main_respects_config_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() passes the --config JSON into generate_image settings."""
    output = tmp_path / "result_cfg.png"
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"selectedFrame": "None"}))

    test_argv = [
        "dry_run_plugin.py",
        "--plugin",
        "year_progress",
        "--output",
        str(output),
        "--config",
        str(settings_file),
    ]
    with patch.object(sys, "argv", test_argv):
        mod = _import_dry_run()
        mod.main()

    assert output.exists()


def test_main_default_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When --output is omitted the file is created in the cwd."""
    # Change working directory to tmp_path so the default path lands there
    monkeypatch.chdir(tmp_path)

    test_argv = [
        "dry_run_plugin.py",
        "--plugin",
        "year_progress",
    ]
    with patch.object(sys, "argv", test_argv):
        mod = _import_dry_run()
        mod.main()

    pngs = list(tmp_path.glob("dry-run-year_progress-*.png"))
    assert len(pngs) == 1, f"Expected one auto-named PNG, found: {pngs}"


# ── record / replay ──────────────────────────────────────────────────────────

_ONECALL_URL = (
    "https://api.openweathermap.org/data/3.0/onecall"
    "?lat=1&lon=2&units=metric&appid=SECRET-KEY"
)


def _fake_network(payload: bytes, content_type: str) -> Any:
    """A transport adapter standing in for the internet."""
    import requests
    from requests.adapters import BaseAdapter

    class _Net(BaseAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def send(self, request: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            resp = requests.Response()
            resp.status_code = 200
            resp.url = request.url
            resp.request = request
            resp._content = payload
            resp.headers["Content-Type"] = content_type
            return resp

        def close(self) -> None:
            return None

    return _Net()


def test_response_key_drops_the_query_so_keys_stay_out_of_file_names(
    dry_run_mod: Any,
) -> None:
    key = dry_run_mod._response_key(_ONECALL_URL)
    assert key == "api.openweathermap.org_data_3.0_onecall.body"
    assert "SECRET" not in key


def test_response_key_separates_hosts_and_paths(dry_run_mod: Any) -> None:
    keys = {
        dry_run_mod._response_key(u)
        for u in (
            "https://api.open-meteo.com/v1/forecast?x=1",
            "https://air-quality-api.open-meteo.com/v1/air-quality?x=1",
            "https://api.openweathermap.org/data/2.5/air_pollution?x=1",
        )
    }
    assert len(keys) == 3


def test_record_then_replay_round_trip(dry_run_mod: Any, tmp_path: Path) -> None:
    import requests

    body = json.dumps({"current": {"temp": 21}}).encode()

    recorder = requests.Session()
    net = _fake_network(body, "application/json; charset=utf-8")
    recorder.mount("https://", net)
    dry_run_mod._start_recording(recorder, tmp_path)
    assert recorder.get(_ONECALL_URL, timeout=5).json() == {"current": {"temp": 21}}
    assert net.calls == 1

    saved = tmp_path / "api.openweathermap.org_data_3.0_onecall.body"
    assert saved.read_bytes() == body
    index_text = (tmp_path / "_index.json").read_text()
    assert "SECRET" not in index_text
    assert json.loads(index_text)[saved.name]["content_type"].startswith(
        "application/json"
    )

    player = requests.Session()
    dry_run_mod._start_replay(player, tmp_path)
    resp = player.get(_ONECALL_URL, timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"current": {"temp": 21}}
    assert resp.headers["Content-Type"].startswith("application/json")


def test_replay_serves_streamed_bytes(dry_run_mod: Any, tmp_path: Path) -> None:
    """Image downloads read with stream=True / iter_content still work."""
    import requests

    (tmp_path / "example.com_pic.png.body").write_bytes(b"\x89PNG-bytes")
    session = requests.Session()
    dry_run_mod._start_replay(session, tmp_path)
    resp = session.get("https://example.com/pic.png", stream=True, timeout=5)
    assert b"".join(resp.iter_content(4)) == b"\x89PNG-bytes"


def test_replay_miss_fails_loudly_without_the_query(
    dry_run_mod: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import requests

    session = requests.Session()
    dry_run_mod._start_replay(session, tmp_path)
    with pytest.raises(requests.ConnectionError) as excinfo:
        session.get(_ONECALL_URL, timeout=5)
    assert "api.openweathermap.org/data/3.0/onecall" in str(excinfo.value)
    assert "SECRET" not in str(excinfo.value)
    assert "replay miss" in capsys.readouterr().err


def test_record_skips_error_responses(dry_run_mod: Any, tmp_path: Path) -> None:
    import requests

    session = requests.Session()
    net = _fake_network(b"nope", "text/plain")
    session.mount("https://", net)
    dry_run_mod._start_recording(session, tmp_path)

    def _fail(response: Any, *args: Any, **kwargs: Any) -> Any:
        response.status_code = 401
        return response

    # Runs before the recorder, the way a real 401 would arrive.
    session.hooks["response"].insert(0, _fail)
    session.get(_ONECALL_URL, timeout=5)
    assert not list(tmp_path.glob("*.body"))


def test_replay_missing_directory_exits(dry_run_mod: Any, tmp_path: Path) -> None:
    import requests

    with pytest.raises(SystemExit, match="--replay directory not found"):
        dry_run_mod._start_replay(requests.Session(), tmp_path / "nope")


# ── vendored-asset warning ───────────────────────────────────────────────────


def test_missing_vendor_files_lists_only_absent_ones(
    dry_run_mod: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "install").mkdir()
    (tmp_path / "install" / "update_vendors.sh").write_text(
        "declare -a VENDORS=(\n"
        '  "Chart JS|https://cdn.example/chart.js|src/static/scripts/chart.js|abc"\n'
        '  "Cal JS|https://cdn.example/cal.js|src/static/scripts/calendar.min.js|def"\n'
        ")\n"
    )
    (tmp_path / "src" / "static" / "scripts").mkdir(parents=True)
    (tmp_path / "src" / "static" / "scripts" / "chart.js").write_text("x")
    monkeypatch.setattr(dry_run_mod, "REPO_ROOT", str(tmp_path))

    assert dry_run_mod._missing_vendor_files() == ["src/static/scripts/calendar.min.js"]


def test_missing_vendor_files_reads_the_real_vendor_list(dry_run_mod: Any) -> None:
    """The parser must keep matching install/update_vendors.sh's format."""
    repo = Path(dry_run_mod.REPO_ROOT)
    text = (repo / "install" / "update_vendors.sh").read_text()
    import re

    listed = re.findall(r'^\s*"[^|"]+\|[^|"]+\|([^|"]+)\|', text, flags=re.M)
    assert "src/static/scripts/chart.js" in listed
    assert set(dry_run_mod._missing_vendor_files()) <= set(listed)

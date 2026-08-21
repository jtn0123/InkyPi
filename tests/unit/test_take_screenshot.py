import importlib
from typing import Any

import pytest
from PIL import Image


def test_take_screenshot_success(monkeypatch: pytest.MonkeyPatch) -> Any:
    import utils.image_utils as image_utils

    # Reload to restore real functions (autouse fixture monkeypatches by default)
    image_utils = importlib.reload(image_utils)

    class Result:
        returncode = 0
        stderr = b""

    monkeypatch.setattr("utils.image_utils.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: True)
    monkeypatch.setattr("utils.image_utils.os.remove", lambda p: None)

    class _Ctx:
        def __init__(self, size: Any = (10, 6)) -> None:
            self._img = Image.new("RGB", size, "white")

        def __enter__(self) -> Any:
            return self._img

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
            return False

    monkeypatch.setattr("utils.image_utils.Image.open", lambda p: _Ctx())

    out = image_utils.take_screenshot("http://example.com", (8, 4), timeout_ms=1234)
    assert out is not None
    assert out.size == (10, 6)


def test_take_screenshot_failure_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    import utils.image_utils as image_utils

    image_utils = importlib.reload(image_utils)

    class Result:
        returncode = 1
        stderr = b"boom"

    monkeypatch.setattr("utils.image_utils.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: False)

    out = image_utils.take_screenshot("http://example.com", (8, 4))
    assert out is None


def test_take_screenshot_passes_timeout_flag(monkeypatch: pytest.MonkeyPatch) -> Any:
    import utils.image_utils as image_utils

    image_utils = importlib.reload(image_utils)

    recorded: dict = {"cmd": []}

    class Result:
        returncode = 0
        stderr = b""

    def fake_run(cmd: Any, **kwargs: Any) -> Any:
        recorded["cmd"] = cmd
        return Result()

    monkeypatch.setattr("utils.image_utils.subprocess.run", fake_run)
    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: True)
    monkeypatch.setattr("utils.image_utils.os.remove", lambda p: None)

    class _Ctx:
        def __init__(self, size: Any = (10, 6)) -> None:
            self._img = Image.new("RGB", size, "white")

        def __enter__(self) -> Any:
            return self._img

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
            return False

    monkeypatch.setattr("utils.image_utils.Image.open", lambda p: _Ctx())

    out = image_utils.take_screenshot("http://example.com", (8, 4), timeout_ms=5678)
    assert out is not None
    # Ensure flag was added
    assert any(
        str(x).startswith("--timeout=") and "5678" in str(x) for x in recorded["cmd"]
    )


def test_take_screenshot_browser_detection_chrome_first(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Test that Google Chrome is tried first when available"""
    import utils.image_utils as image_utils

    image_utils = importlib.reload(image_utils)

    recorded: dict[str, list[list[str]]] = {"cmds": []}

    class Result:
        returncode = 0
        stderr = b""

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        cmd = args[0] if args else kwargs.get("cmd", [])
        recorded["cmds"].append(cmd)
        return Result()

    monkeypatch.setattr("utils.image_utils.subprocess.run", fake_run)

    def mock_exists(p: Any) -> Any:
        if p == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome":
            return True
        # Also return True for the temporary screenshot file
        return bool(p and p.endswith(".png") and ("/tmp/" in p or "/T/" in p))

    monkeypatch.setattr("utils.image_utils.os.path.exists", mock_exists)
    monkeypatch.setattr("utils.image_utils.os.remove", lambda p: None)

    class _Ctx:
        def __init__(self, size: Any = (10, 6)) -> None:
            self._img = Image.new("RGB", size, "white")

        def __enter__(self) -> Any:
            return self._img

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
            return False

    monkeypatch.setattr("utils.image_utils.Image.open", lambda p: _Ctx())

    out = image_utils.take_screenshot("http://example.com", (8, 4))
    assert out is not None
    # Should use Google Chrome first
    cmd_str = str(recorded["cmds"][0])
    assert "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" in cmd_str


def test_take_screenshot_browser_fallback_to_chromium(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Test fallback to chromium when Chrome is not available"""
    import utils.image_utils as image_utils

    image_utils = importlib.reload(image_utils)

    recorded: dict[str, list[list[str]]] = {"cmds": []}

    class Result:
        returncode = 0
        stderr = b""

    def fake_run(cmd: Any, **kwargs: Any) -> Any:
        recorded["cmds"].append(cmd)
        return Result()

    def mock_exists(p: Any) -> Any:
        # Return True for temporary screenshot files
        return bool(p and p.endswith(".png") and ("/tmp/" in p or "/T/" in p))

    monkeypatch.setattr("utils.image_utils.subprocess.run", fake_run)
    monkeypatch.setattr("utils.image_utils.os.path.exists", mock_exists)
    monkeypatch.setattr("utils.image_utils.os.remove", lambda p: None)
    monkeypatch.setattr(
        "utils.image_utils.shutil.which",
        lambda b: (
            b if b in ["chromium", "chromium-headless-shell", "google-chrome"] else None
        ),
    )

    class _Ctx:
        def __init__(self, size: Any = (10, 6)) -> None:
            self._img = Image.new("RGB", size, "white")

        def __enter__(self) -> Any:
            return self._img

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
            return False

    monkeypatch.setattr("utils.image_utils.Image.open", lambda p: _Ctx())

    out = image_utils.take_screenshot("http://example.com", (8, 4))
    assert out is not None
    # Should have tried one of the fallback browsers
    cmd_str = str(recorded["cmds"][0])
    assert any(
        browser in cmd_str
        for browser in ["chromium", "chromium-headless-shell", "google-chrome"]
    )


def test_take_screenshot_no_browser_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error handling when no browsers are available"""
    import utils.image_utils as image_utils

    image_utils = importlib.reload(image_utils)

    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: False)
    monkeypatch.setattr("utils.image_utils.shutil.which", lambda b: None)

    out = image_utils.take_screenshot("http://example.com", (8, 4))
    assert out is None

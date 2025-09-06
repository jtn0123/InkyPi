import importlib
from io import BytesIO
from PIL import Image


def test_take_screenshot_success(monkeypatch):
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
        def __init__(self, size=(10, 6)):
            self._img = Image.new("RGB", size, "white")
        def __enter__(self):
            return self._img
        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("utils.image_utils.Image.open", lambda p: _Ctx())

    out = image_utils.take_screenshot("http://example.com", (8, 4), timeout_ms=1234)
    assert out is not None
    assert out.size == (10, 6)


def test_take_screenshot_failure_nonzero(monkeypatch):
    import utils.image_utils as image_utils
    image_utils = importlib.reload(image_utils)

    class Result:
        returncode = 1
        stderr = b"boom"

    monkeypatch.setattr("utils.image_utils.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: False)

    out = image_utils.take_screenshot("http://example.com", (8, 4))
    assert out is None


def test_take_screenshot_passes_timeout_flag(monkeypatch):
    import utils.image_utils as image_utils
    image_utils = importlib.reload(image_utils)

    recorded: dict = {"cmd": []}

    class Result:
        returncode = 0
        stderr = b""

    def fake_run(cmd, stdout=None, stderr=None):
        recorded["cmd"] = cmd
        return Result()

    monkeypatch.setattr("utils.image_utils.subprocess.run", fake_run)
    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: True)
    monkeypatch.setattr("utils.image_utils.os.remove", lambda p: None)

    class _Ctx:
        def __init__(self, size=(10, 6)):
            self._img = Image.new("RGB", size, "white")
        def __enter__(self):
            return self._img
        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("utils.image_utils.Image.open", lambda p: _Ctx())

    out = image_utils.take_screenshot("http://example.com", (8, 4), timeout_ms=5678)
    assert out is not None
    # Ensure flag was added
    assert any(str(x).startswith("--timeout=") and "5678" in str(x) for x in recorded["cmd"]) 



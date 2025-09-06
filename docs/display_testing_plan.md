### Display Drivers Testing Plan

This plan targets robust, hardware-agnostic tests for the display layer: `DisplayManager`, `MockDisplay`, `InkyDisplay`, and `WaveshareDisplay`.

---

### Scope and Priorities

- Primary: Validate `DisplayManager` image pipeline (save → orientation → resize → enhancements → delegate).
- Secondary: Validate driver init and render calls for `MockDisplay`, `InkyDisplay`, `WaveshareDisplay` with external APIs mocked.

---

### Fixtures and Mocks

- Use existing `device_config_dev` fixture for isolated config and output directories.
- For `InkyDisplay`: monkeypatch `inky.auto.auto` to return a fake object with `width`, `height`, `set_border`, `set_image`, and `show` methods; assert calls.
- For `WaveshareDisplay`: monkeypatch `importlib.import_module` to return a stub module with class `EPD` exposing `width`, `height`, `Init/init`, `display`, `getbuffer`, `Clear`, and `sleep`; cover both mono and bi-color paths via different stubs.
- For `DisplayManager`: monkeypatch `utils.image_utils` functions to observe that they were called with expected arguments; use in-memory PIL images.

---

### Test Cases

1) DisplayManager
- Saves original image to `Config.current_image_file` path.
- Applies orientation based on `orientation` setting.
- Resizes to `get_resolution()` and respects `image_settings` and `keep-width` flag.
- Delegates to selected display type: `mock`, `inky`, `epd7in3e` (waveshare-like), error on unsupported type.

2) MockDisplay
- `initialize_display` is a no-op; log message only.
- `display_image` writes `display_*.png` and `latest.png` to `output_dir`.

3) InkyDisplay
- On init: calls `auto()`, sets border, writes resolution if missing.
- On display: `set_image` then `show`; raises ValueError if `image` is None.

4) WaveshareDisplay
- On init: loads `EPD` from dynamic module name; calls `Init`/`init`; writes resolution if missing.
- On display (mono): calls `Init`, `Clear`, `display(getbuffer(image))`, then `sleep`.
- On display (bi-color): passes two buffers; creates 1-bit color layer.
- Raises ValueError on missing/unsupported module or missing required methods.

---

### Validation

- Run `pytest -q` and `pytest --cov=src --cov-report=term-missing`.
- Target: raise display package coverage from ~12–24% to 60%+.



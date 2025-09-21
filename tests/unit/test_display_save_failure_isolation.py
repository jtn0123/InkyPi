from PIL import Image


def test_display_continue_on_save_failures(monkeypatch, device_config_dev):
    # Prepare display manager and image
    device_config_dev.update_value("display_type", "mock")
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)

    # Spy hardware display call
    called = {"render": 0}

    def spy_render(img, image_settings=None):
        called["render"] += 1

    monkeypatch.setattr(dm.display, "display_image", spy_render, raising=True)

    # Force save failures for processed preview and history copies, but allow the first
    # current_image save to succeed
    original_save = Image.Image.save

    def conditional_fail_save(self, fp, *args, **kwargs):
        # Allow saving the initial current image, fail others
        if str(fp) == device_config_dev.current_image_file:
            return original_save(self, fp, *args, **kwargs)
        raise RuntimeError("disk full")

    monkeypatch.setattr(Image.Image, "save", conditional_fail_save, raising=True)

    # Run display; failures should be logged but not crash; render should still be called
    img = Image.new("RGB", (64, 48), "white")
    try:
        dm.display_image(img, image_settings=[], history_meta={"k": "v"})
    except Exception as e:
        # Should not raise due to save failures
        raise AssertionError(f"display_image should tolerate save failures: {e}")

    assert called["render"] == 1


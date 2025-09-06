def test_screenshot_success(monkeypatch, device_config_dev):
    from plugins.screenshot.screenshot import Screenshot

    # Success is covered by autouse fixture replacing take_screenshot
    img = Screenshot({"id": "screenshot"}).generate_image(
        {"url": "http://example.com"}, device_config_dev
    )
    assert img is not None
    assert img.size == tuple(device_config_dev.get_resolution())


def test_screenshot_failure(monkeypatch, device_config_dev):
    from plugins.screenshot.screenshot import Screenshot

    # Force take_screenshot to return None at the import location used by plugin
    monkeypatch.setattr(
        "plugins.screenshot.screenshot.take_screenshot",
        lambda *a, **k: None,
        raising=True,
    )

    try:
        Screenshot({"id": "screenshot"}).generate_image(
            {"url": "http://example.com"}, device_config_dev
        )
        assert False, "Expected failure when screenshot cannot be taken"
    except RuntimeError:
        pass

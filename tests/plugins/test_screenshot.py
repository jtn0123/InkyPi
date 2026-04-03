import socket

import pytest


def test_screenshot_success(monkeypatch, device_config_dev):
    from plugins.screenshot.screenshot import Screenshot

    # Mock DNS resolution to return a public IP so validate_url passes
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )

    # Success is covered by autouse fixture replacing take_screenshot
    img = Screenshot({"id": "screenshot"}).generate_image(
        {"url": "http://example.com"}, device_config_dev
    )
    assert img is not None
    assert img.size == tuple(device_config_dev.get_resolution())


def test_screenshot_failure(monkeypatch, device_config_dev):
    from plugins.screenshot.screenshot import Screenshot

    # Mock DNS resolution to return a public IP so validate_url passes
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )

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


def test_screenshot_rejects_file_url(device_config_dev):
    """Screenshot plugin must reject file:// URLs."""
    from plugins.screenshot.screenshot import Screenshot

    plugin = Screenshot({"id": "screenshot"})
    with pytest.raises(RuntimeError, match="Invalid URL"):
        plugin.generate_image({"url": "file:///etc/passwd"}, device_config_dev)


def test_screenshot_rejects_localhost(device_config_dev):
    """Screenshot plugin must reject localhost URLs."""
    from plugins.screenshot.screenshot import Screenshot

    plugin = Screenshot({"id": "screenshot"})
    with pytest.raises(RuntimeError, match="Invalid URL"):
        plugin.generate_image({"url": "http://localhost:8080"}, device_config_dev)


def test_screenshot_rejects_metadata_endpoint(monkeypatch, device_config_dev):
    """Screenshot plugin must reject cloud metadata endpoints."""
    from plugins.screenshot.screenshot import Screenshot

    # 169.254.169.254 is link-local — mock DNS so it resolves to that IP
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))
        ],
    )

    plugin = Screenshot({"id": "screenshot"})
    with pytest.raises(RuntimeError, match="Invalid URL"):
        plugin.generate_image(
            {"url": "http://169.254.169.254/latest/meta-data/"}, device_config_dev
        )

import socket

import pytest


def test_image_url_happy(monkeypatch, device_config_dev):
    from plugins.image_url.image_url import ImageURL

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr(
        "plugins.image_url.image_url.fetch_and_resize_remote_image",
        lambda *args, **kwargs: object(),
    )

    img = ImageURL({"id": "image_url"}).generate_image(
        {"url": "http://example.com/img.jpg"}, device_config_dev
    )
    assert img is not None


def test_image_url_missing_url(device_config_dev):
    from plugins.image_url.image_url import ImageURL

    try:
        ImageURL({"id": "image_url"}).generate_image({}, device_config_dev)
        assert False, "Expected error"
    except RuntimeError:
        pass


def test_image_url_rejects_localhost(device_config_dev):
    """ImageURL plugin must reject localhost URLs."""
    from plugins.image_url.image_url import ImageURL

    plugin = ImageURL({"id": "image_url"})
    with pytest.raises(RuntimeError, match="Invalid URL"):
        plugin.generate_image({"url": "http://localhost/image.jpg"}, device_config_dev)


def test_image_url_rejects_private_ip(monkeypatch, device_config_dev):
    """ImageURL plugin must reject private IP addresses."""
    from plugins.image_url.image_url import ImageURL

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0))
        ],
    )

    plugin = ImageURL({"id": "image_url"})
    with pytest.raises(RuntimeError, match="Invalid URL"):
        plugin.generate_image(
            {"url": "http://internal.example.com/image.jpg"}, device_config_dev
        )


def test_image_url_rejects_metadata_endpoint(monkeypatch, device_config_dev):
    """ImageURL plugin must reject cloud metadata endpoints."""
    from plugins.image_url.image_url import ImageURL

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))
        ],
    )

    plugin = ImageURL({"id": "image_url"})
    with pytest.raises(RuntimeError, match="Invalid URL"):
        plugin.generate_image(
            {"url": "http://169.254.169.254/latest/meta-data/"}, device_config_dev
        )

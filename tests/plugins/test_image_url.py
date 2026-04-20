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


@pytest.mark.parametrize(
    "bad_url,expected_fragment",
    [
        ("file:///etc/passwd", "scheme"),
        ("http://127.0.0.1/", "private"),
        ("http://169.254.169.254/", "private"),
        ("http://", "hostname"),
    ],
)
def test_image_url_raises_url_validation_error(bad_url, expected_fragment):
    """JTN-776: plugins must raise URLValidationError (not bare RuntimeError)
    on bad URLs so the blueprint can map it to HTTP 422."""
    from plugins.image_url.image_url import ImageURL
    from utils.security_utils import URLValidationError

    plugin = ImageURL({"id": "image_url"})
    with pytest.raises(URLValidationError) as exc_info:
        plugin.generate_image({"url": bad_url}, device_config=None)
    assert expected_fragment in str(exc_info.value)


def test_image_url_validate_settings_uses_shared_validator(monkeypatch):
    from plugins.image_url.image_url import ImageURL

    seen = {}

    def fake_validate_url(url):
        seen["url"] = url
        raise ValueError("URL scheme must be http or https")

    monkeypatch.setattr("plugins.image_url.image_url.validate_url", fake_validate_url)

    plugin = ImageURL({"id": "image_url"})
    error = plugin.validate_settings({"url": "  ftp://example.com/image.png  "})
    assert error == "URL scheme must be http or https"
    assert seen["url"] == "ftp://example.com/image.png"

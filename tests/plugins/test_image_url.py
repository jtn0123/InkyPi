import socket
from typing import Any
from unittest.mock import MagicMock

import pytest


def test_image_url_happy(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
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


def test_image_url_missing_url(device_config_dev: Any) -> None:
    from plugins.image_url.image_url import ImageURL

    try:
        ImageURL({"id": "image_url"}).generate_image({}, device_config_dev)
        assert False, "Expected error"
    except RuntimeError:
        pass


def test_image_url_rejects_localhost(device_config_dev: Any) -> None:
    """ImageURL plugin must reject localhost URLs."""
    from plugins.image_url.image_url import ImageURL

    plugin = ImageURL({"id": "image_url"})
    with pytest.raises(RuntimeError, match="Invalid URL"):
        plugin.generate_image({"url": "http://localhost/image.jpg"}, device_config_dev)


def test_image_url_rejects_private_ip(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
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


def test_image_url_rejects_metadata_endpoint(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
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
def test_image_url_raises_url_validation_error(
    bad_url: Any, expected_fragment: Any
) -> None:
    """JTN-776: plugins must raise URLValidationError (not bare RuntimeError)
    on bad URLs so the blueprint can map it to HTTP 422."""
    from plugins.image_url.image_url import ImageURL
    from utils.plugin_errors import URLValidationError

    plugin = ImageURL({"id": "image_url"})
    with pytest.raises(URLValidationError) as exc_info:
        plugin.generate_image({"url": bad_url}, device_config=None)
    assert expected_fragment in str(exc_info.value)


def test_image_url_validate_settings_uses_shared_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plugins.image_url.image_url import ImageURL

    seen = {}

    def fake_validate_url(url: Any, **kwargs: Any) -> None:
        seen["url"] = url
        raise ValueError("URL scheme must be http or https")

    monkeypatch.setattr("plugins.image_url.image_url.validate_url", fake_validate_url)

    plugin = ImageURL({"id": "image_url"})
    error = plugin.validate_settings({"url": "  ftp://example.com/image.png  "})
    assert error == "URL scheme must be http or https"
    assert seen["url"] == "ftp://example.com/image.png"


def _resolve_to(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))],
    )


TAILNET_URL = "http://camera.tailnet.example/snapshot.jpg"


def test_tailscale_image_url_needs_the_lan_opt_in(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    """100.64.0.0/10 is refused unless INKYPI_ALLOW_PRIVATE_FEEDS is set."""
    from plugins.image_url.image_url import ImageURL
    from utils.plugin_errors import URL_ERR_PRIVATE_FEED, URLValidationError

    monkeypatch.delenv("INKYPI_ALLOW_PRIVATE_FEEDS", raising=False)
    _resolve_to(monkeypatch, "100.101.102.103")
    fetch = MagicMock()
    monkeypatch.setattr(
        "plugins.image_url.image_url.fetch_and_resize_remote_image", fetch
    )
    plugin = ImageURL({"id": "image_url"})

    assert plugin.validate_settings({"url": TAILNET_URL}) == URL_ERR_PRIVATE_FEED
    with pytest.raises(URLValidationError) as excinfo:
        plugin.generate_image({"url": TAILNET_URL}, device_config_dev)
    assert excinfo.value.reason == URL_ERR_PRIVATE_FEED
    fetch.assert_not_called()


def test_tailscale_image_url_works_with_the_lan_opt_in(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    from PIL import Image

    from plugins.image_url.image_url import ImageURL

    monkeypatch.setenv("INKYPI_ALLOW_PRIVATE_FEEDS", "1")
    _resolve_to(monkeypatch, "100.101.102.103")
    fetch = MagicMock(return_value=Image.new("RGB", (8, 6)))
    monkeypatch.setattr(
        "plugins.image_url.image_url.fetch_and_resize_remote_image", fetch
    )
    plugin = ImageURL({"id": "image_url"})

    assert plugin.validate_settings({"url": TAILNET_URL}) is None
    assert plugin.generate_image({"url": TAILNET_URL}, device_config_dev) is not None
    assert fetch.call_args.kwargs["allow_lan"] is True


def test_the_lan_opt_in_still_refuses_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plugins.image_url.image_url import ImageURL
    from utils.plugin_errors import URL_ERR_PRIVATE

    monkeypatch.setenv("INKYPI_ALLOW_PRIVATE_FEEDS", "1")
    _resolve_to(monkeypatch, "127.0.0.1")
    plugin = ImageURL({"id": "image_url"})
    assert plugin.validate_settings({"url": TAILNET_URL}) == URL_ERR_PRIVATE


@pytest.mark.parametrize("allow_lan", [False, True])
def test_remote_image_fetch_applies_the_opt_in_to_every_hop(
    monkeypatch: pytest.MonkeyPatch, allow_lan: bool
) -> None:
    import utils.image_utils as image_utils

    _resolve_to(monkeypatch, "100.101.102.103")
    fetched: list[str] = []

    def fake_http_get(url: str, **kwargs: Any) -> Any:
        fetched.append(url)
        raise RuntimeError("stop after the first request")

    monkeypatch.setattr(image_utils, "http_get", fake_http_get)
    assert (
        image_utils.fetch_and_resize_remote_image(
            TAILNET_URL, (8, 6), allow_lan=allow_lan
        )
        is None
    )
    assert fetched == ([TAILNET_URL] if allow_lan else [])

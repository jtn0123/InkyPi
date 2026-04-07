# pyright: reportMissingImports=false
import socket
from contextlib import ExitStack, contextmanager
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

# A fake public DNS response used by tests that need validate_url to pass.
_PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _png_bytes(size=(100, 80), color="blue"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def plugin_config():
    return {"id": "image_album", "class": "ImageAlbum", "name": "Image Album"}


def _make_mock_session(albums, assets, image_bytes):
    """Build a mock session whose .get/.post return appropriate data."""
    session = MagicMock()
    search_calls = {"count": 0}

    def fake_get(url, **kw):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "/api/albums" in url:
            resp.json.return_value = albums
        elif "/api/assets/" in url and "/original" in url:
            resp.content = image_bytes
            resp.iter_content = MagicMock(return_value=[image_bytes])
        return resp

    def fake_post(url, **kw):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        items = assets if search_calls["count"] == 0 else []
        search_calls["count"] += 1
        resp.json.return_value = {"assets": {"items": items}}
        return resp

    session.get = MagicMock(side_effect=fake_get)
    session.post = MagicMock(side_effect=fake_post)
    return session


@contextmanager
def _patched_album_sessions(session):
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "plugins.image_album.image_album.get_http_session",
                return_value=session,
            )
        )
        stack.enter_context(
            patch("utils.image_loader.get_http_session", return_value=session)
        )
        yield


def test_image_album_generate_success(monkeypatch, plugin_config, device_config_dev):
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setenv("IMMICH_KEY", "test-key")
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _PUBLIC_DNS)

    albums = [{"albumName": "Vacation", "id": "album-1"}]
    assets = [{"id": "asset-1"}]
    img_bytes = _png_bytes()

    session = _make_mock_session(albums, assets, img_bytes)
    with _patched_album_sessions(session):
        p = ImageAlbum(plugin_config)
        result = p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://immich.example.com",
                "album": "Vacation",
            },
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_image_album_missing_key(monkeypatch, plugin_config, device_config_dev):
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.delenv("IMMICH_KEY", raising=False)
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: None)

    p = ImageAlbum(plugin_config)
    with pytest.raises(RuntimeError, match="API Key"):
        p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://immich.example.com",
                "album": "Vacation",
            },
            device_config_dev,
        )


def test_image_album_missing_url(monkeypatch, plugin_config, device_config_dev):
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")

    p = ImageAlbum(plugin_config)
    with pytest.raises(RuntimeError, match="URL is required"):
        p.generate_image(
            {"albumProvider": "Immich", "url": "", "album": "Vacation"},
            device_config_dev,
        )


def test_image_album_missing_album(monkeypatch, plugin_config, device_config_dev):
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _PUBLIC_DNS)

    p = ImageAlbum(plugin_config)
    with pytest.raises(RuntimeError, match="Album name"):
        p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://immich.example.com",
                "album": "",
            },
            device_config_dev,
        )


def test_image_album_unsupported_provider(
    monkeypatch, plugin_config, device_config_dev
):
    from plugins.image_album.image_album import ImageAlbum

    p = ImageAlbum(plugin_config)
    with pytest.raises(RuntimeError, match="Unsupported album provider"):
        p.generate_image(
            {"albumProvider": "UnknownProvider", "url": "http://x", "album": "x"},
            device_config_dev,
        )


def test_image_album_empty_assets(monkeypatch, plugin_config, device_config_dev):
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _PUBLIC_DNS)

    albums = [{"albumName": "Empty", "id": "album-2"}]
    session = _make_mock_session(albums, [], _png_bytes())
    with _patched_album_sessions(session):
        p = ImageAlbum(plugin_config)
        with pytest.raises(RuntimeError, match="Failed to load image"):
            p.generate_image(
                {
                    "albumProvider": "Immich",
                    "url": "http://immich.example.com",
                    "album": "Empty",
                },
                device_config_dev,
            )


def test_image_album_padding_blur(monkeypatch, plugin_config, device_config_dev):
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _PUBLIC_DNS)

    albums = [{"albumName": "Photos", "id": "album-3"}]
    assets = [{"id": "asset-2"}]
    img_bytes = _png_bytes()

    session = _make_mock_session(albums, assets, img_bytes)
    with _patched_album_sessions(session):
        p = ImageAlbum(plugin_config)
        result = p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://immich.example.com",
                "album": "Photos",
                "padImage": "true",
                "backgroundOption": "blur",
            },
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_image_album_padding_color(monkeypatch, plugin_config, device_config_dev):
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _PUBLIC_DNS)

    albums = [{"albumName": "Photos", "id": "album-3"}]
    assets = [{"id": "asset-2"}]
    img_bytes = _png_bytes()

    session = _make_mock_session(albums, assets, img_bytes)
    with _patched_album_sessions(session):
        p = ImageAlbum(plugin_config)
        result = p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://immich.example.com",
                "album": "Photos",
                "padImage": "true",
                "backgroundOption": "color",
                "backgroundColor": "#ff0000",
            },
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_image_album_rejects_localhost_url(
    monkeypatch, plugin_config, device_config_dev
):
    """ImageAlbum plugin must reject localhost Immich base URLs."""
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")

    p = ImageAlbum(plugin_config)
    with pytest.raises(RuntimeError, match="Invalid URL"):
        p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://localhost:2283",
                "album": "Vacation",
            },
            device_config_dev,
        )


def test_image_album_rejects_private_ip_url(
    monkeypatch, plugin_config, device_config_dev
):
    """ImageAlbum plugin must reject private IP Immich base URLs."""
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 0))
        ],
    )

    p = ImageAlbum(plugin_config)
    with pytest.raises(RuntimeError, match="Invalid URL"):
        p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://internal.corp.example.com:2283",
                "album": "Vacation",
            },
            device_config_dev,
        )


def test_image_album_rejects_metadata_endpoint_url(
    monkeypatch, plugin_config, device_config_dev
):
    """ImageAlbum plugin must reject cloud metadata endpoint Immich base URLs."""
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))
        ],
    )

    p = ImageAlbum(plugin_config)
    with pytest.raises(RuntimeError, match="Invalid URL"):
        p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://169.254.169.254",
                "album": "Vacation",
            },
            device_config_dev,
        )


def test_image_album_vertical(monkeypatch, plugin_config, device_config_dev):
    from plugins.image_album.image_album import ImageAlbum

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "test-key")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _PUBLIC_DNS)
    device_config_dev.update_value("orientation", "vertical")

    albums = [{"albumName": "Vacation", "id": "album-1"}]
    assets = [{"id": "asset-1"}]
    img_bytes = _png_bytes()

    session = _make_mock_session(albums, assets, img_bytes)
    with _patched_album_sessions(session):
        p = ImageAlbum(plugin_config)
        result = p.generate_image(
            {
                "albumProvider": "Immich",
                "url": "http://immich.example.com",
                "album": "Vacation",
            },
            device_config_dev,
        )
    assert isinstance(result, Image.Image)

from typing import Any

import pytest


def test_apod_decode_failure(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> Any:
    from plugins.apod.apod import Apod

    p = Apod({"id": "apod"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "fake")

    # The API answers with a picture URL whose bytes are not an image. Both
    # the plugin and the image loader use the shared plugin session.
    class R:
        status_code = 200

        def json(self) -> Any:
            return {"media_type": "image", "url": "https://example.com/x.png"}

    class R2:
        status_code = 200
        content = b"not-an-image"

        def raise_for_status(self) -> None:
            pass

        def iter_content(self, chunk_size: int = 8192) -> Any:
            yield self.content

    requested: list[str] = []

    class Session:
        def get(self, url: str, **kwargs: Any) -> Any:
            requested.append(url)
            return R() if url.endswith("/planetary/apod") else R2()

    monkeypatch.setattr("plugins.apod.apod.get_http_session", lambda: Session())
    monkeypatch.setattr("utils.image_loader.get_http_session", lambda: Session())

    with pytest.raises(RuntimeError, match="Failed to load APOD image"):
        p.generate_image({}, device_config_dev)
    assert requested[1:] == ["https://example.com/x.png"]


def test_unsplash_decode_failure(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> Any:
    from plugins.unsplash.unsplash import Unsplash

    u = Unsplash({"id": "unsplash"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "fake")

    # Mock Unsplash API JSON
    class R:
        status_code = 200

        def json(self) -> Any:
            return {"urls": {"full": "https://example.com/x.jpg"}}

        def raise_for_status(self) -> None:
            pass  # No error

    monkeypatch.setattr("requests.get", lambda *a, **k: R(), raising=True)

    # Make grab_image return None (decode failure path)
    monkeypatch.setattr(
        "plugins.unsplash.unsplash.grab_image", lambda *a, **k: None, raising=True
    )

    with pytest.raises(RuntimeError):
        u.generate_image({}, device_config_dev)


def test_image_url_decode_failure(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.image_url.image_url import ImageURL

    p = ImageURL({"id": "image_url"})

    # Make grab_image return None (decode failure path)
    monkeypatch.setattr(
        "plugins.image_url.image_url.grab_image", lambda *a, **k: None, raising=True
    )

    with pytest.raises(RuntimeError):
        p.generate_image({"url": "https://example.com/x.png"}, device_config_dev)

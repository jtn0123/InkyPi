def test_image_url_happy(monkeypatch, device_config_dev):
    from plugins.image_url.image_url import ImageURL

    monkeypatch.setattr(
        "plugins.image_url.image_url.fetch_and_resize_remote_image",
        lambda *args, **kwargs: object(),
    )

    img = ImageURL({"id": "image_url"}).generate_image(
        {"url": "http://img"}, device_config_dev
    )
    assert img is not None


def test_image_url_missing_url(device_config_dev):
    from plugins.image_url.image_url import ImageURL

    try:
        ImageURL({"id": "image_url"}).generate_image({}, device_config_dev)
        assert False, "Expected error"
    except RuntimeError:
        pass

from io import BytesIO
from PIL import Image


def _png_bytes(size=(10, 6), color="white"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_wpotd_happy_path(monkeypatch, device_config_dev):
    from plugins.wpotd.wpotd import Wpotd

    def fake_session_get(self, url, params=None, headers=None, timeout=None):
        class R:
            status_code = 200
            def raise_for_status(self):
                return None
            def json(self_inner):
                if params and params.get("prop") == "images":
                    return {"query": {"pages": [{"images": [{"title": "File:Example.png"}]}]}}
                if params and params.get("prop") == "imageinfo":
                    return {"query": {"pages": {"1": {"imageinfo": [{"url": "http://example.com/img.png"}]}}}}
                return {}

        return R()

    # Patch requests.Session.get so Wpotd.SESSION.get uses our fake
    import requests
    monkeypatch.setattr(requests.Session, "get", fake_session_get, raising=True)

    # Patch download step to avoid PIL open complexities
    import plugins.wpotd.wpotd as wpotd_mod
    monkeypatch.setattr(wpotd_mod.Wpotd, "_download_image", lambda self, u: Image.open(BytesIO(_png_bytes())).copy())

    img = Wpotd({"id": "wpotd"}).generate_image({"shrinkToFitWpotd": "false"}, device_config_dev)
    assert img is not None
    assert img.size[0] > 0


def test_wpotd_bad_status_raises(monkeypatch, device_config_dev):
    from plugins.wpotd.wpotd import Wpotd

    class BadResp:
        status_code = 500
        def raise_for_status(self):
            raise RuntimeError("boom")
        def json(self):
            return {}

    def fake_session_get(self, url, params=None, headers=None, timeout=None):
        return BadResp()

    import requests
    monkeypatch.setattr(requests.Session, "get", fake_session_get, raising=True)

    try:
        Wpotd({"id": "wpotd"}).generate_image({}, device_config_dev)
        assert False, "Expected Wikipedia API request failure"
    except RuntimeError:
        pass


def test_wpotd_missing_fields_raises(monkeypatch, device_config_dev):
    from plugins.wpotd.wpotd import Wpotd

    def fake_session_get(self, url, params=None, headers=None, timeout=None):
        class R:
            status_code = 200
            def raise_for_status(self):
                return None
            def json(self_inner):
                # Missing images array content
                return {"query": {"pages": [{"images": []}]}}
        return R()

    import requests
    monkeypatch.setattr(requests.Session, "get", fake_session_get, raising=True)

    try:
        Wpotd({"id": "wpotd"}).generate_image({}, device_config_dev)
        assert False, "Expected failure to retrieve POTD filename"
    except RuntimeError:
        pass

 
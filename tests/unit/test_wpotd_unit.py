from datetime import date, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image

import plugins.wpotd.wpotd as wpotd_mod


class DummyDevice:
    def __init__(self, resolution=(100, 100)):
        self._resolution = resolution

    def get_resolution(self):
        return self._resolution


def make_png_bytes():
    bio = BytesIO()
    Image.new('RGB', (10, 10), color=(10, 20, 30)).save(bio, format='PNG')
    return bio.getvalue()


def test_determine_date_custom():
    p = wpotd_mod.Wpotd({'id': 'wpotd'})
    d = p._determine_date({'customDate': '2020-02-03'})
    assert d == date(2020, 2, 3)


def test_download_image_svg_unsupported():
    p = wpotd_mod.Wpotd({'id': 'wpotd'})
    with pytest.raises(RuntimeError):
        p._download_image('http://example.com/file.svg')


def test_download_image_unidentified(monkeypatch):
    p = wpotd_mod.Wpotd({'id': 'wpotd'})

    class Resp:
        content = b'notanimage'

        def raise_for_status(self):
            return None

    monkeypatch.setattr(wpotd_mod.Wpotd, 'SESSION', type('S', (), {'get': staticmethod(lambda *a, **k: Resp())}))

    with pytest.raises(RuntimeError):
        p._download_image('http://example.com/image.png')


def test_download_image_success(monkeypatch):
    p = wpotd_mod.Wpotd({'id': 'wpotd'})
    content = make_png_bytes()

    class Resp:
        def __init__(self, c):
            self.content = c

        def raise_for_status(self):
            return None

    monkeypatch.setattr(wpotd_mod.Wpotd, 'SESSION', type('S', (), {'get': staticmethod(lambda *a, **k: Resp(content))}))
    img = p._download_image('http://example.com/image.png')
    assert isinstance(img, Image.Image)


def test_fetch_potd_and_fetch_image_src(monkeypatch):
    p = wpotd_mod.Wpotd({'id': 'wpotd'})

    # Mock _make_request to first return a structure with images list
    def fake_make_request_first(params):
        return {'query': {'pages': [{'images': [{'title': 'File:Example.png'}]}]}}

    monkeypatch.setattr(wpotd_mod.Wpotd, '_make_request', staticmethod(fake_make_request_first))
    monkeypatch.setattr(wpotd_mod.Wpotd, '_fetch_image_src', staticmethod(lambda filename: 'http://example.com/img.png'))

    result = p._fetch_potd(date(2021, 1, 1))
    assert result['filename'] == 'File:Example.png'
    assert result['image_src'] == 'http://example.com/img.png'


def test_fetch_potd_missing_images(monkeypatch):
    p = wpotd_mod.Wpotd({'id': 'wpotd'})
    monkeypatch.setattr(wpotd_mod.Wpotd, '_make_request', staticmethod(lambda params: {}))
    with pytest.raises(RuntimeError):
        p._fetch_potd(date(2021, 1, 1))


def test_fetch_image_src_success_and_missing(monkeypatch):
    p = wpotd_mod.Wpotd({'id': 'wpotd'})

    # success case
    data = {'query': {'pages': {'123': {'imageinfo': [{'url': 'http://x.png'}]}}}}
    monkeypatch.setattr(wpotd_mod.Wpotd, '_make_request', staticmethod(lambda params: data))
    url = p._fetch_image_src('File:Example.png')
    assert url == 'http://x.png'

    # missing url
    data2 = {'query': {'pages': {'123': {'imageinfo': [{}]}}}}
    monkeypatch.setattr(wpotd_mod.Wpotd, '_make_request', staticmethod(lambda params: data2))
    with pytest.raises(RuntimeError):
        p._fetch_image_src('File:NoUrl.png')


def test_shrink_to_fit_no_change_and_resize():
    p = wpotd_mod.Wpotd({'id': 'wpotd'})
    # small image, no resize
    img = Image.new('RGB', (10, 10), 'white')
    out = p._shrink_to_fit(img, 100, 100)
    assert out.size == (10, 10)

    # larger image, will be resized and padded
    img2 = Image.new('RGB', (200, 100), 'white')
    out2 = p._shrink_to_fit(img2, 50, 50)
    assert out2.size == (50, 50)



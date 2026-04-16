from datetime import date
from io import BytesIO
from typing import Any

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
    Image.new("RGB", (10, 10), color=(10, 20, 30)).save(bio, format="PNG")
    return bio.getvalue()


def test_determine_date_custom():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    d = p._determine_date({"customDate": "2020-02-03"})
    assert d == date(2020, 2, 3)


def test_determine_date_invalid_custom_date_falls_back(monkeypatch):
    p = wpotd_mod.Wpotd({"id": "wpotd"})

    class FrozenDateTime:
        @staticmethod
        def today():
            return datetime(2024, 1, 2)

        @staticmethod
        def now(tz=None):
            # Mirror today(); tests pin the date, tz is ignored.
            return datetime(2024, 1, 2)

        @staticmethod
        def strptime(value, fmt):
            return datetime.strptime(value, fmt)

    from datetime import datetime

    monkeypatch.setattr(wpotd_mod, "datetime", FrozenDateTime)
    d = p._determine_date({"customDate": "2024-99-99"})
    assert d == date(2024, 1, 2)


def test_download_image_svg_unsupported():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    with pytest.raises(RuntimeError):
        p._download_image("http://example.com/file.svg")


def test_download_image_unidentified(monkeypatch):
    p = wpotd_mod.Wpotd({"id": "wpotd"})

    monkeypatch.setattr(p.image_loader, "from_url", lambda *a, **k: None)

    with pytest.raises(RuntimeError):
        p._download_image("http://example.com/image.png")


def test_download_image_success(monkeypatch):
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    fake_image = Image.new("RGB", (10, 10), "white")

    monkeypatch.setattr(p.image_loader, "from_url", lambda *a, **k: fake_image)
    img = p._download_image("http://example.com/image.png")
    assert img is fake_image


def test_fetch_potd_and_fetch_image_src(monkeypatch):
    p = wpotd_mod.Wpotd({"id": "wpotd"})

    # Mock _make_request to first return a structure with images list
    def fake_make_request_first(params):
        return {"query": {"pages": [{"images": [{"title": "File:Example.png"}]}]}}

    monkeypatch.setattr(
        wpotd_mod.Wpotd, "_make_request", staticmethod(fake_make_request_first)
    )
    monkeypatch.setattr(
        wpotd_mod.Wpotd,
        "_fetch_image_src",
        staticmethod(lambda filename: "http://example.com/img.png"),
    )

    result = p._fetch_potd(date(2021, 1, 1))
    assert result["filename"] == "File:Example.png"
    assert result["image_src"] == "http://example.com/img.png"


def test_fetch_potd_missing_images(monkeypatch):
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    monkeypatch.setattr(
        wpotd_mod.Wpotd, "_make_request", staticmethod(lambda params: {})
    )
    with pytest.raises(RuntimeError):
        p._fetch_potd(date(2021, 1, 1))


def test_fetch_image_src_success_and_missing(monkeypatch):
    p = wpotd_mod.Wpotd({"id": "wpotd"})

    # success case
    data = {"query": {"pages": {"123": {"imageinfo": [{"url": "http://x.png"}]}}}}
    monkeypatch.setattr(
        wpotd_mod.Wpotd, "_make_request", staticmethod(lambda params: data)
    )
    url = p._fetch_image_src("File:Example.png")
    assert url == "http://x.png"

    # missing url
    data2: dict[str, Any] = {"query": {"pages": {"123": {"imageinfo": [{}]}}}}
    monkeypatch.setattr(
        wpotd_mod.Wpotd, "_make_request", staticmethod(lambda params: data2)
    )
    with pytest.raises(RuntimeError):
        p._fetch_image_src("File:NoUrl.png")


def test_shrink_to_fit_no_change_and_resize():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    # small image, no resize
    img = Image.new("RGB", (10, 10), "white")
    out = p._shrink_to_fit(img, 100, 100)
    assert out.size == (10, 10)

    # larger image, will be resized and padded
    img2 = Image.new("RGB", (200, 100), "white")
    out2 = p._shrink_to_fit(img2, 50, 50)
    assert out2.size == (50, 50)


# ---------------------------------------------------------------------------
# validate_settings tests
# ---------------------------------------------------------------------------


def test_wpotd_validate_settings_rejects_date_before_archive():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    err = p.validate_settings({"customDate": "1990-01-01"})
    assert err is not None
    assert "Wikipedia POTD archive start" in err


def test_wpotd_validate_settings_rejects_future_date():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    err = p.validate_settings({"customDate": "9999-12-31"})
    assert err is not None
    assert "on or before" in err


def test_wpotd_validate_settings_rejects_malformed_date():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    err = p.validate_settings({"customDate": "not-a-date"})
    assert err is not None
    assert "Invalid date format" in err


def test_wpotd_validate_settings_ignores_date_when_randomized():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    err = p.validate_settings({"randomizeWpotd": "true", "customDate": "1990-01-01"})
    assert err is None


def test_wpotd_validate_settings_accepts_blank_custom_date():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    assert p.validate_settings({"customDate": ""}) is None
    assert p.validate_settings({}) is None


def test_wpotd_validate_settings_accepts_valid_date():
    p = wpotd_mod.Wpotd({"id": "wpotd"})
    assert p.validate_settings({"customDate": "2023-01-01"}) is None

import os
import random

import pytest
from PIL import Image

import plugins.image_upload.image_upload as image_upload_mod


class DummyDeviceConfig:
    def __init__(self, resolution=(100, 200), orientation='horizontal'):
        self._resolution = resolution
        self._orientation = orientation

    def get_resolution(self):
        return self._resolution

    def get_config(self, key):
        if key == 'orientation':
            return self._orientation
        return None


def make_png_file(path, size=(10, 10), color=(255, 0, 0)):
    img = Image.new('RGB', size, color=color)
    img.save(path, format='PNG')


def test_open_image_success(tmp_path):
    p = tmp_path / 'img.png'
    make_png_file(p)
    u = image_upload_mod.ImageUpload({'id': 'image_upload'})
    img = u.open_image(0, [str(p)])
    assert isinstance(img, Image.Image)


def test_open_image_no_images():
    u = image_upload_mod.ImageUpload({'id': 'image_upload'})
    with pytest.raises(RuntimeError):
        u.open_image(0, [])


def test_open_image_bad_path():
    u = image_upload_mod.ImageUpload({'id': 'image_upload'})
    with pytest.raises(RuntimeError):
        u.open_image(0, ['/non/existent/path.png'])


def test_generate_image_no_images():
    u = image_upload_mod.ImageUpload({'id': 'image_upload'})
    settings = {}
    with pytest.raises(RuntimeError):
        u.generate_image(settings, DummyDeviceConfig())


def test_generate_image_index_wrap_and_increment(tmp_path):
    # create two images
    p1 = tmp_path / 'a.png'
    p2 = tmp_path / 'b.png'
    make_png_file(p1, size=(50, 50))
    make_png_file(p2, size=(20, 40))

    settings = {'image_index': 5, 'imageFiles[]': [str(p1), str(p2)]}
    u = image_upload_mod.ImageUpload({'id': 'image_upload'})
    out = u.generate_image(settings, DummyDeviceConfig(resolution=(30, 30)))
    # image_index should have been reset to 0 then incremented to 1
    assert settings['image_index'] == 1
    assert isinstance(out, Image.Image)


def test_generate_image_randomize(monkeypatch, tmp_path):
    p1 = tmp_path / 'a.png'
    p2 = tmp_path / 'b.png'
    make_png_file(p1, size=(10, 10))
    make_png_file(p2, size=(20, 20))

    settings = {'image_index': 0, 'imageFiles[]': [str(p1), str(p2)], 'randomize': 'true'}
    # force random.randrange to pick index 1
    monkeypatch.setattr(random, 'randrange', lambda a, b: 1)
    u = image_upload_mod.ImageUpload({'id': 'image_upload'})
    out = u.generate_image(settings, DummyDeviceConfig(resolution=(15, 15)))
    assert isinstance(out, Image.Image)


def test_generate_image_padImage_true(tmp_path):
    p = tmp_path / 'wide.png'
    # wide image
    make_png_file(p, size=(200, 50))

    settings = {'image_index': 0, 'imageFiles[]': [str(p)], 'padImage': 'true', 'backgroundColor': 'rgb(255,255,255)'}
    u = image_upload_mod.ImageUpload({'id': 'image_upload'})
    device = DummyDeviceConfig(resolution=(100, 200))
    out = u.generate_image(settings, device)
    # When padding, returned image should match the padded size computed
    frame_ratio = device.get_resolution()[0] / device.get_resolution()[1]
    img_width, img_height = Image.open(str(p)).size
    padded_w = int(img_height * frame_ratio) if img_width >= img_height else img_width
    padded_h = img_height if img_width >= img_height else int(img_width / frame_ratio)
    assert out.size == (padded_w, padded_h)



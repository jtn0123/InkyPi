import os
import socket
import subprocess
from io import BytesIO

import pytest
from PIL import Image

from src.utils import app_utils


class FakeForm:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)

    def keys(self):
        return list(self._data.keys())

    def getlist(self, key):
        return self._data.get(key)

    def get(self, key, default=None):
        return self._data.get(key, default)


class FakeFile:
    def __init__(self, filename, content_bytes):
        self.filename = filename
        self.stream = BytesIO(content_bytes)

    def read(self):
        # simulate reading entire file
        self.stream.seek(0)
        return self.stream.read()

    def seek(self, pos):
        self.stream.seek(pos)

    def tell(self):
        return self.stream.tell()


class FakeFiles:
    """Mimic the subset of a Werkzeug MultiDict used by handle_request_files."""

    def __init__(self, pairs):
        # pairs: list of (key, file)
        self._pairs = list(pairs)

    def keys(self):
        return {k for (k, _v) in self._pairs}

    def items(self, multi=False):
        # when called with multi=True, return iterator of pairs
        return iter(self._pairs)


def test_resolve_path_with_env(tmp_path, monkeypatch):
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    p = app_utils.resolve_path('static/images')
    assert str(tmp_path).replace('\\', '/') in p.replace('\\', '/')


def test_parse_form_list_handling():
    form = FakeForm({'a': '1', 'b[]': ['x', 'y']})
    parsed = app_utils.parse_form(form)
    assert parsed['a'] == '1'
    assert parsed['b[]'] == ['x', 'y']


def test_get_wifi_name_success(monkeypatch):
    monkeypatch.setattr(subprocess, 'check_output', lambda *_args, **_kwargs: b'my-network\n')
    assert app_utils.get_wifi_name() == 'my-network'


def test_get_wifi_name_failure(monkeypatch):
    def _raise(*_a, **_k):
        raise subprocess.CalledProcessError(1, ['iwgetid'])

    monkeypatch.setattr(subprocess, 'check_output', _raise)
    assert app_utils.get_wifi_name() is None


def test_is_connected_true_false(monkeypatch):
    # True case: create_connection does not raise
    monkeypatch.setattr(socket, 'create_connection', lambda *_a, **_k: True)
    assert app_utils.is_connected() is True

    # False case: create_connection raises OSError
    def _raise(*_a, **_k):
        raise OSError()

    monkeypatch.setattr(socket, 'create_connection', _raise)
    assert app_utils.is_connected() is False


def make_png_bytes():
    bio = BytesIO()
    Image.new('RGB', (10, 10), color=(255, 0, 0)).save(bio, format='PNG')
    return bio.getvalue()


def test_handle_request_files_valid_image(tmp_path, monkeypatch):
    # Ensure uploads are saved under a temporary SRC_DIR
    monkeypatch.setenv('SRC_DIR', str(tmp_path))

    content = make_png_bytes()
    f = FakeFile('test.png', content)
    files = FakeFiles([('file', f)])

    result = app_utils.handle_request_files(files)
    assert 'file' in result
    saved_path = result['file']
    assert os.path.exists(saved_path)


def test_handle_request_files_large_file(tmp_path, monkeypatch):
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    monkeypatch.setenv('MAX_UPLOAD_BYTES', '10')

    content = make_png_bytes()
    # ensure content is larger than 10 bytes
    assert len(content) > 10

    f = FakeFile('big.png', content)
    files = FakeFiles([('file', f)])

    with pytest.raises(RuntimeError):
        app_utils.handle_request_files(files)


def test_handle_request_files_invalid_image(tmp_path, monkeypatch):
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    f = FakeFile('notimg.png', b'notanimage')
    files = FakeFiles([('file', f)])

    with pytest.raises(Exception):
        app_utils.handle_request_files(files)

# pyright: reportMissingImports=false
from werkzeug.datastructures import ImmutableMultiDict, CombinedMultiDict, FileStorage
from io import BytesIO
from PIL import Image

from utils.app_utils import parse_form, handle_request_files


def test_parse_form_with_list_fields():
    form = ImmutableMultiDict([('a', '1'), ('b[]', 'x'), ('b[]', 'y')])
    out = parse_form(form)
    assert out['a'] == '1'
    assert out['b[]'] == ['x', 'y']


def test_handle_request_files_saves_images(tmp_path, monkeypatch):
    # Prepare a simple PNG in memory
    buf = BytesIO()
    Image.new('RGB', (10, 10), 'white').save(buf, format='PNG')
    buf.seek(0)

    fs = FileStorage(stream=buf, filename='test.png', content_type='image/png')
    files = CombinedMultiDict([ImmutableMultiDict(), ImmutableMultiDict([('file', fs)])])

    # Ensure files are written to tmp path by overriding resolve_path base
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    (tmp_path / 'static' / 'images' / 'saved').mkdir(parents=True, exist_ok=True)

    out = handle_request_files(files)
    assert 'file' in out
    assert out['file'].endswith('test.png')


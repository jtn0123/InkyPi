import os
import socket
import subprocess
from io import BytesIO

import pytest
from PIL import Image

import utils.app_utils as app_utils


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


def test_get_ip_address(monkeypatch):
    """Test get_ip_address function."""
    import socket
    mock_socket = type('MockSocket', (), {
        'AF_INET': socket.AF_INET,
        'SOCK_DGRAM': socket.SOCK_DGRAM,
        'connect': lambda self, addr: None,
        'getsockname': lambda self: ('192.168.1.100', 12345),
        '__enter__': lambda self: self,
        '__exit__': lambda self, *args: None
    })()

    def mock_socket_constructor(*args, **kwargs):
        return mock_socket

    monkeypatch.setattr(socket, 'socket', mock_socket_constructor)
    result = app_utils.get_ip_address()
    assert result == '192.168.1.100'


def test_get_font_valid(monkeypatch, tmp_path):
    """Test get_font with valid font family."""
    from PIL import ImageFont

    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    # Create a mock font file
    fonts_dir = tmp_path / 'static' / 'fonts'
    fonts_dir.mkdir(parents=True)
    font_file = fonts_dir / 'Jost.ttf'
    font_file.write_bytes(b'mock font data')

    # Mock ImageFont.truetype to return a mock font object
    mock_font = type('MockFont', (), {})()
    monkeypatch.setattr(ImageFont, 'truetype', lambda *args, **kwargs: mock_font)

    result = app_utils.get_font('Jost', 24, 'normal')
    assert result is mock_font


def test_get_font_invalid_family():
    """Test get_font with invalid font family."""
    result = app_utils.get_font('InvalidFont', 24, 'normal')
    assert result is None


def test_get_font_invalid_weight(monkeypatch, tmp_path):
    """Test get_font with invalid weight for valid family."""
    from PIL import ImageFont

    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    fonts_dir = tmp_path / 'static' / 'fonts'
    fonts_dir.mkdir(parents=True)
    font_file = fonts_dir / 'Jost.ttf'
    font_file.write_bytes(b'mock font data')

    # Mock ImageFont.truetype to return a mock font object
    mock_font = type('MockFont', (), {})()
    monkeypatch.setattr(ImageFont, 'truetype', lambda *args, **kwargs: mock_font)

    result = app_utils.get_font('Jost', 24, 'invalid_weight')
    # Should fall back to first available variant
    assert result is mock_font


def test_get_fonts(monkeypatch, tmp_path):
    """Test get_fonts function."""
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    fonts_dir = tmp_path / 'static' / 'fonts'
    fonts_dir.mkdir(parents=True)

    # Create mock font files
    for font_name, variants in app_utils.FONT_FAMILIES.items():
        for variant in variants:
            font_file = fonts_dir / variant['file']
            font_file.write_bytes(b'mock font data')

    result = app_utils.get_fonts()
    assert isinstance(result, list)
    assert len(result) > 0

    # Check structure of first item
    item = result[0]
    assert 'font_family' in item
    assert 'url' in item
    assert 'font_weight' in item
    assert 'font_style' in item


def test_get_font_path(monkeypatch, tmp_path):
    """Test get_font_path function."""
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    result = app_utils.get_font_path('jost')
    expected = str(tmp_path / 'static' / 'fonts' / 'Jost.ttf')
    assert result == expected


def test_generate_startup_image(monkeypatch, tmp_path):
    """Test generate_startup_image function."""
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    fonts_dir = tmp_path / 'static' / 'fonts'
    fonts_dir.mkdir(parents=True)

    # Create mock font file
    font_file = fonts_dir / 'Jost.ttf'
    font_file.write_bytes(b'mock font data')

    # Mock socket functions
    import socket
    monkeypatch.setattr(socket, 'gethostname', lambda: 'test-host')
    mock_socket = type('MockSocket', (), {
        'AF_INET': socket.AF_INET,
        'SOCK_DGRAM': socket.SOCK_DGRAM,
        'connect': lambda self, addr: None,
        'getsockname': lambda self: ('192.168.1.100', 12345),
        '__enter__': lambda self: self,
        '__exit__': lambda self, *args: None
    })()

    def mock_socket_constructor(*args, **kwargs):
        return mock_socket

    monkeypatch.setattr(socket, 'socket', mock_socket_constructor)

    result = app_utils.generate_startup_image((400, 300))
    assert isinstance(result, Image.Image)
    assert result.size == (400, 300)
    assert result.mode == 'RGBA'


def test_handle_request_files_form_data_fallback(monkeypatch, tmp_path):
    """Test handle_request_files with form data fallback."""
    monkeypatch.setenv('SRC_DIR', str(tmp_path))

    # Create a mock files object that doesn't support .keys()
    class MockFiles:
        def __init__(self, items):
            self._items = items

        def items(self, multi=True):
            return iter(self._items)

    # Test the fallback code path
    files = MockFiles([('file', FakeFile('test.png', make_png_bytes()))])
    form_data = {'existing_key': 'existing_value'}

    result = app_utils.handle_request_files(files, form_data)
    assert isinstance(result, dict)


def test_handle_request_files_getlist_fallback(monkeypatch, tmp_path):
    """Test handle_request_files with getlist fallback."""
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    (tmp_path / 'static' / 'images' / 'saved').mkdir(parents=True, exist_ok=True)

    # Mock form_data without getlist method
    class MockFormData(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        def get(self, key, default=None):
            return super().get(key, default)

    form_data = MockFormData({'file[]': ['existing_path1', 'existing_path2']})
    files = FakeFiles([])  # Empty files

    result = app_utils.handle_request_files(files, form_data)
    assert 'file[]' in result
    assert result['file[]'] == ['existing_path1', 'existing_path2']


def test_handle_request_files_max_upload_env(monkeypatch, tmp_path):
    """Test handle_request_files with MAX_UPLOAD_BYTES environment variable."""
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    monkeypatch.setenv('MAX_UPLOAD_BYTES', '100')

    content = make_png_bytes()
    f = FakeFile('test.png', content)
    files = FakeFiles([('file', f)])

    # This should work since our test image is small
    result = app_utils.handle_request_files(files)
    assert 'file' in result


def test_handle_request_files_empty_content(monkeypatch, tmp_path):
    """Test handle_request_files with empty file content."""
    monkeypatch.setenv('SRC_DIR', str(tmp_path))

    # Create a fake file with empty content
    f = FakeFile('empty.png', b'')
    files = FakeFiles([('file', f)])

    with pytest.raises(RuntimeError, match="Empty upload content"):
        app_utils.handle_request_files(files)


def test_handle_request_files_list_mode(monkeypatch, tmp_path):
    """Test handle_request_files with list mode (key ending with [])."""
    monkeypatch.setenv('SRC_DIR', str(tmp_path))
    (tmp_path / 'static' / 'images' / 'saved').mkdir(parents=True, exist_ok=True)

    content = make_png_bytes()
    f = FakeFile('test.png', content)
    files = FakeFiles([('files[]', f)])

    result = app_utils.handle_request_files(files)
    assert 'files[]' in result
    assert isinstance(result['files[]'], list)
    assert len(result['files[]']) == 1


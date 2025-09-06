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


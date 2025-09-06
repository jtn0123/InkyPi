import importlib.util
from pathlib import Path


def test_api_keys_page_loads(client):
    resp = client.get('/settings/api-keys')
    assert resp.status_code == 200


def test_save_api_keys_and_read_back(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    # Save a key
    resp = client.post('/settings/save_api_keys', data={
        'NASA_SECRET': 'route-test-123'
    })
    assert resp.status_code == 200
    # Read back via config API
    # Dynamically import config.py
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec and spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    assert cfg.load_env_key('NASA_SECRET') == 'route-test-123'


def test_delete_api_key(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    # Prime .env
    src_dir = Path(__file__).resolve().parents[2] / "src"
    spec = importlib.util.spec_from_file_location("config", str(src_dir / "config.py"))
    assert spec and spec.loader
    config_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_mod)
    cfg = config_mod.Config()
    cfg.set_env_key('NASA_SECRET', 'to-delete')

    # Delete via route
    resp = client.post('/settings/delete_api_key', data={'key': 'NASA_SECRET'})
    assert resp.status_code == 200

    # Ensure removed
    assert cfg.load_env_key('NASA_SECRET') is None



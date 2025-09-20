import importlib
import sys


def _reload_inkypi(monkeypatch, argv=None, env=None):
    if argv is None:
        argv = ["inkypi.py"]
    if env is None:
        env = {}

    # Reset influencing env
    for key in [
        "INKYPI_ENV",
        "FLASK_ENV",
        "INKYPI_CONFIG_FILE",
        "SECRET_KEY",
        "PROJECT_DIR",
        "INKYPI_NO_REFRESH",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(sys, "argv", argv)

    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]

    import inkypi  # noqa: F401
    mod = importlib.reload(sys.modules["inkypi"])
    mod.main(argv[1:])
    return mod


def _register_test_routes(app):
    from utils.http_utils import APIError, json_success

    @app.route("/raise_api_error")
    def _raise_api_error():
        raise APIError("boom", status=418, code="X")

    @app.route("/ok")
    def _ok():
        return json_success("OK")


def test_request_id_propagates_in_json_error(monkeypatch):
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    app = getattr(mod, "app", None)
    assert app is not None

    _register_test_routes(app)
    client = app.test_client()

    r = client.get(
        "/raise_api_error",
        headers={
            "Accept": "application/json",
            "X-Request-Id": "rid-123",
        },
    )
    assert r.status_code == 418
    body = r.get_json()
    assert body.get("error") == "boom"
    assert body.get("request_id") == "rid-123"


def test_request_id_propagates_in_json_success(monkeypatch):
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    app = getattr(mod, "app", None)
    assert app is not None

    _register_test_routes(app)
    client = app.test_client()

    r = client.get(
        "/ok",
        headers={
            "Accept": "application/json",
            "X-Request-Id": "rid-456",
        },
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("success") is True
    assert body.get("message") == "OK"
    assert body.get("request_id") == "rid-456"


def test_hot_reload_header_emitted_in_dev(monkeypatch):
    # Ensure DEV mode
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    app = getattr(mod, "app", None)
    assert app is not None

    # Monkeypatch the imported function within inkypi module
    monkeypatch.setattr(
        "inkypi.pop_hot_reload_info",
        lambda: {"plugin_id": "foo", "reloaded": True},
        raising=True,
    )

    client = app.test_client()
    r = client.get("/healthz")

    # Header should be set when DEV_MODE and info present
    hdr = r.headers.get("X-InkyPi-Hot-Reload")
    assert hdr == "foo:1"



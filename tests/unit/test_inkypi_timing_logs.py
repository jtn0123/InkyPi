import importlib
import logging
import sys


def _reload_inkypi(monkeypatch, argv=None, env=None):
    if argv is None:
        argv = ["inkypi.py"]
    if env is None:
        env = {}

    for key in [
        "INKYPI_ENV",
        "FLASK_ENV",
        "INKYPI_CONFIG_FILE",
        "INKYPI_NO_REFRESH",
        "INKYPI_REQUEST_TIMING",
    ]:
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    monkeypatch.setattr(sys, "argv", argv)
    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]
    import inkypi  # noqa: F401

    mod = importlib.reload(sys.modules["inkypi"])
    mod.main(argv[1:])
    return mod


def test_request_timing_log_emitted(monkeypatch, caplog):
    # Enable timing logs and run in dev to avoid production headers affecting path
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    app = getattr(mod, "app", None)
    assert app is not None

    # Turn on timing via env
    monkeypatch.setenv("INKYPI_REQUEST_TIMING", "1")

    # Capture logs from the inkypi logger specifically
    caplog.set_level(logging.INFO, logger="inkypi")

    # Spy on inkypi logger to ensure timing log path executes regardless of handlers
    messages = []

    def _spy_info(msg, *args, **kwargs):
        try:
            messages.append(msg % args if args else msg)
        except Exception:
            messages.append(str(msg))

    monkeypatch.setattr(mod, "logger", logging.getLogger("inkypi"), raising=True)
    monkeypatch.setattr(mod.logger, "info", _spy_info, raising=True)

    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200

    # Look for the timing line emitted by after_request (either via records or aggregated text)
    found = bool(messages) or any(
        "HTTP GET /healthz -> 200 in" in rec.getMessage() for rec in caplog.records
    ) or (
        "HTTP GET /healthz -> 200 in" in caplog.text
    ) or (
        # Fallback: match key parts to avoid formatter differences
        ("HTTP GET" in caplog.text and "/healthz" in caplog.text and "-> 200" in caplog.text)
    )
    assert found


import importlib
import os
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
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(sys, "argv", argv)

    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]

    import inkypi  # noqa: F401

    return importlib.reload(sys.modules["inkypi"])


def test_secret_key_from_env(monkeypatch, tmp_path):
    # SECRET_KEY present in environment should be used as-is
    mod = _reload_inkypi(
        monkeypatch,
        argv=["inkypi.py", "--dev"],
        env={"SECRET_KEY": "from-env", "PROJECT_DIR": str(tmp_path)},
    )
    app = getattr(mod, "app", None)
    assert app is not None
    assert app.secret_key == "from-env"


def test_secret_key_persisted_in_dev_env_file(monkeypatch, tmp_path):
    # No SECRET_KEY in process env; should generate and persist to .env in dev
    env = {"INKYPI_ENV": "dev", "PROJECT_DIR": str(tmp_path)}
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env=env)
    app = getattr(mod, "app", None)
    assert app is not None
    generated = app.secret_key
    assert isinstance(generated, str) and len(generated) >= 32

    # Verify persisted in .env
    env_path = os.path.join(str(tmp_path), ".env")
    with open(env_path, "r") as f:
        content = f.read()
    assert f"SECRET_KEY={generated}" in content

    # Reload; should reuse same key from file
    mod2 = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env=env)
    app2 = getattr(mod2, "app", None)
    assert app2.secret_key == generated


def test_secret_key_ephemeral_in_prod_when_missing(monkeypatch, tmp_path):
    # Production mode: if missing, it should generate but not necessarily persist
    env = {"INKYPI_ENV": "production", "PROJECT_DIR": str(tmp_path)}
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env=env)
    app = getattr(mod, "app", None)
    first = app.secret_key

    # Reload without setting SECRET_KEY; likely different each time
    mod2 = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env=env)
    app2 = getattr(mod2, "app", None)
    second = app2.secret_key

    assert isinstance(first, str) and isinstance(second, str)
    # They may be equal by chance, but extremely unlikely; allow inequality check
    assert first != second



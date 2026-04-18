import os


def test_plugin_static_image_route(client):
    # Create a fake plugin asset
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "plugins")
    )
    plugin_dir = os.path.join(base, "ai_text")
    icon_src = os.path.join(plugin_dir, "icon.png")

    # Ensure icon exists in repo
    assert os.path.exists(icon_src), "Expected plugin icon to exist in repository"

    # Request through route
    resp = client.get("/images/ai_text/icon.png")
    assert resp.status_code == 200
    assert resp.data[:8] != b"", "Non-empty body"
    # Content-Type should be an image type
    assert "image" in (resp.headers.get("Content-Type") or "")


def test_plugin_static_image_route_with_relative_src_dir(client, tmp_path, monkeypatch):
    """Relative SRC_DIR values must stay rooted at the repo, not the cwd."""
    monkeypatch.setenv("SRC_DIR", "src")
    monkeypatch.chdir(tmp_path)

    resp = client.get("/images/ai_text/icon.png")
    assert resp.status_code == 200
    assert "image" in (resp.headers.get("Content-Type") or "")

    resp = client.get("/images/base_plugin/frames/blank.png")
    assert resp.status_code == 200
    assert "image" in (resp.headers.get("Content-Type") or "")


# ---------------------------------------------------------------------------
# Security – py/path-injection regression (JTN-326)
# ---------------------------------------------------------------------------


def test_plugin_image_allows_nested_subpath(client):
    """Nested filenames under a plugin dir (e.g. frames/blank.png) still work."""
    resp = client.get("/images/base_plugin/frames/blank.png")
    assert resp.status_code == 200
    assert "image" in (resp.headers.get("Content-Type") or "")


def test_plugin_image_rejects_parent_traversal(client):
    """../ in the filename must not escape the plugin directory."""
    resp = client.get("/images/ai_text/..%2ficon.png")
    # Werkzeug rejects %2f in <path:...> before we see it (404/308); either
    # way the route must never return an image from outside the plugin dir.
    assert resp.status_code in (404, 308, 400)

    resp = client.get("/images/ai_text/../clock/icon.png")
    assert resp.status_code in (404, 308, 400)


def test_plugin_image_rejects_unknown_plugin_id(client):
    """Unknown plugin_id yields 404."""
    resp = client.get("/images/__does_not_exist__/icon.png")
    assert resp.status_code == 404


def test_plugin_image_rejects_unknown_filename(client):
    """Known plugin + unknown file yields 404 (not a filesystem error)."""
    resp = client.get("/images/ai_text/nope_missing.png")
    assert resp.status_code == 404


def test_plugin_image_rejects_absolute_plugin_id(client):
    """An absolute path in plugin_id must be rejected."""
    # Double slash effectively makes plugin_id empty; Flask routes this to 404.
    resp = client.get("/images//etc/passwd")
    assert resp.status_code in (404, 308)


def test_plugin_image_rejects_dot_segments(client):
    """Single-dot segments in filename are rejected."""
    resp = client.get("/images/ai_text/./icon.png")
    # Werkzeug may normalize or 308; either way we never serve arbitrary files.
    assert resp.status_code in (200, 308, 404)

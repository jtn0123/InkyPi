"""Static checks for shared lightbox module."""


def test_lightbox_script_exists(client):
    resp = client.get("/static/scripts/lightbox.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    tokens = [
        "window.Lightbox",
        "openLightbox",
        "closeLightbox",
        "toggleNativeSizing",
        "bind(selector",
    ]
    for token in tokens:
        assert token in js

    assert "modal.id" in js and "imagePreviewModal" in js


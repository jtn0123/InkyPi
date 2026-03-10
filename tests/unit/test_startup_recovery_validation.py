import os

from PIL import Image


def test_history_page_ignores_truncated_sidecar_json(client, device_config_dev):
    history_dir = device_config_dev.history_image_dir
    image_path = os.path.join(history_dir, "display_20250101_000000.png")
    sidecar_path = os.path.join(history_dir, "display_20250101_000000.json")

    Image.new("RGB", (20, 20), "white").save(image_path)
    with open(sidecar_path, "w", encoding="utf-8") as handle:
        handle.write("{bad json")

    response = client.get("/history")
    assert response.status_code == 200


def test_preview_falls_back_to_current_image_when_processed_missing(client, device_config_dev):
    current_path = device_config_dev.current_image_file
    processed_path = device_config_dev.processed_image_file

    Image.new("RGB", (20, 20), "white").save(current_path)
    if os.path.exists(processed_path):
        os.remove(processed_path)

    response = client.get("/preview")
    assert response.status_code == 200
    assert response.mimetype == "image/png"


def test_refresh_info_endpoint_handles_broken_refresh_info(client, device_config_dev):
    class BrokenRefreshInfo:
        def to_dict(self):
            raise RuntimeError("bad metadata")

    device_config_dev.refresh_info = BrokenRefreshInfo()
    response = client.get("/refresh-info")
    assert response.status_code == 200
    assert response.get_json() == {}


def test_history_storage_returns_actionable_error_when_stat_fails(client, monkeypatch):
    monkeypatch.setattr(
        "shutil.disk_usage",
        lambda path: (_ for _ in ()).throw(OSError("no stat")),
        raising=True,
    )

    response = client.get("/history/storage")
    assert response.status_code == 500
    body = response.get_json()
    assert body["success"] is False
    assert "failed to get storage info" in body["error"]

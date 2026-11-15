# pyright: reportMissingImports=false
"""Image Upload keeps earlier images when new ones are added.

The page lists images that are already on the device as hidden
``imageFiles[]`` form fields holding their paths, and sends newly picked files
as uploads under the same name. Every plugin route must keep the saved paths
and add the new files after them; Save settings and Update instance also
report the stored paths so the page can list them as saved files.
"""

from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

import plugins.image_upload.image_upload as image_upload_mod
import utils.app_utils as app_utils
from blueprints.plugin._common import _plugin_form_data

FIELD = "imageFiles[]"


@pytest.fixture
def saved_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Send uploads to a temp folder instead of src/static/images/saved."""
    saved = tmp_path / "saved"
    saved.mkdir()
    real_resolve_path = app_utils.resolve_path
    upload_dir = os.path.join("static", "images", "saved")

    def resolve_path(file_path: Any) -> str:
        if os.fspath(file_path) == upload_dir:
            return str(saved)
        return real_resolve_path(file_path)

    monkeypatch.setattr(app_utils, "resolve_path", resolve_path)
    monkeypatch.setattr(image_upload_mod, "_get_upload_dir", lambda: str(saved))
    return saved


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="PNG")
    return buf.getvalue()


def _saved_image(saved_dir: Path, name: str = "1700000000_beach.png") -> str:
    path = saved_dir / name
    path.write_bytes(_png_bytes())
    return str(path)


def _new_upload(name: str = "garden.png") -> tuple[BytesIO, str]:
    return (BytesIO(_png_bytes()), name)


def _assert_kept_then_added(paths: list[str], existing: str, saved_dir: Path) -> None:
    assert len(paths) == 2, paths
    assert paths[0] == existing
    added = Path(paths[1])
    assert added.parent == saved_dir
    assert added.name.endswith("_garden.png")
    assert added.is_file()


def test_form_data_keeps_saved_images_beside_new_uploads(
    flask_app: Flask, saved_dir: Path
) -> None:
    existing = _saved_image(saved_dir)
    with flask_app.test_request_context(
        "/update_now",
        method="POST",
        data={"plugin_id": "image_upload", FIELD: [existing, _new_upload()]},
        content_type="multipart/form-data",
    ):
        form_data = _plugin_form_data()

    _assert_kept_then_added(form_data[FIELD], existing, saved_dir)


def test_form_data_without_new_uploads_keeps_saved_images(
    flask_app: Flask, saved_dir: Path
) -> None:
    first = _saved_image(saved_dir)
    second = _saved_image(saved_dir, "1700000001_forest.png")
    with flask_app.test_request_context(
        "/update_now",
        method="POST",
        data={"plugin_id": "image_upload", FIELD: [first, second]},
    ):
        form_data = _plugin_form_data()

    assert form_data[FIELD] == [first, second]


def test_htmx_save_stores_new_images_and_reports_their_paths(
    client: FlaskClient, flask_app: Flask, saved_dir: Path
) -> None:
    existing = _saved_image(saved_dir)
    resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "image_upload",
            "fitMode": "cover",
            FIELD: [existing, _new_upload()],
        },
        content_type="multipart/form-data",
        headers={"HX-Request": "true"},
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    trigger = json.loads(resp.headers["HX-Trigger"])["pluginSettingsSaved"]
    saved_paths = trigger["saved_files"][FIELD]
    _assert_kept_then_added(saved_paths, existing, saved_dir)

    playlist_manager = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    instance = playlist_manager.find_plugin(
        "image_upload", "image_upload_saved_settings"
    )
    assert instance is not None
    assert instance.settings[FIELD] == saved_paths


def test_json_save_reports_stored_paths(client: FlaskClient, saved_dir: Path) -> None:
    existing = _saved_image(saved_dir)
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_upload", FIELD: [existing, _new_upload()]},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    _assert_kept_then_added(resp.get_json()["saved_files"][FIELD], existing, saved_dir)


def test_save_without_uploads_reports_no_saved_files(
    client: FlaskClient, saved_dir: Path
) -> None:
    existing = _saved_image(saved_dir)
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_upload", FIELD: [existing]},
        headers={"HX-Request": "true"},
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    trigger = json.loads(resp.headers["HX-Trigger"])["pluginSettingsSaved"]
    assert trigger["saved_files"] == {}


def test_update_instance_keeps_saved_images_and_reports_paths(
    client: FlaskClient, flask_app: Flask, saved_dir: Path
) -> None:
    existing = _saved_image(saved_dir)
    playlist_manager = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    if not playlist_manager.get_playlist("Default"):
        playlist_manager.add_playlist("Default")
    playlist_manager.get_playlist("Default").add_plugin(
        {
            "plugin_id": "image_upload",
            "name": "Holiday photos",
            "plugin_settings": {FIELD: [existing]},
            "refresh": {"interval": 3600},
        }
    )

    resp = client.put(
        "/update_plugin_instance/Holiday photos",
        data={"plugin_id": "image_upload", FIELD: [existing, _new_upload()]},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    saved_paths = resp.get_json()["saved_files"][FIELD]
    _assert_kept_then_added(saved_paths, existing, saved_dir)
    instance = playlist_manager.find_plugin("image_upload", "Holiday photos")
    assert instance is not None
    assert instance.settings[FIELD] == saved_paths

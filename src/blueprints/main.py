import os

from flask import Blueprint, current_app, render_template, send_file

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def main_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    return render_template(
        "inky.html",
        config=device_config.get_config(),
        plugins=device_config.get_plugins(),
    )


@main_bp.route("/preview")
def preview_image():
    device_config = current_app.config["DEVICE_CONFIG"]
    # Prefer processed image; fall back to current raw image if missing
    path = device_config.processed_image_file
    if not os.path.exists(path):
        path = device_config.current_image_file
    if not os.path.exists(path):
        return ("Preview not available", 404)
    return send_file(path, mimetype="image/png", conditional=True)

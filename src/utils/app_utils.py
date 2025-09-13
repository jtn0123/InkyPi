import logging
import os
import socket
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from utils.image_utils import load_image_from_bytes

logger = logging.getLogger(__name__)

FONT_FAMILIES = {
    "Dogica": [
        {"font-weight": "normal", "file": "dogicapixel.ttf"},
        {"font-weight": "bold", "file": "dogicapixelbold.ttf"},
    ],
    "Jost": [
        {"font-weight": "normal", "file": "Jost.ttf"},
        {"font-weight": "bold", "file": "Jost-SemiBold.ttf"},
    ],
    "Napoli": [{"font-weight": "normal", "file": "Napoli.ttf"}],
    "DS-Digital": [
        {"font-weight": "normal", "file": os.path.join("DS-DIGI", "DS-DIGI.TTF")}
    ],
}

FONTS = {
    "ds-gigi": "DS-DIGI.TTF",
    "napoli": "Napoli.ttf",
    "jost": "Jost.ttf",
    "jost-semibold": "Jost-SemiBold.ttf",
}


def resolve_path(file_path):
    src_dir = os.getenv("SRC_DIR")
    if src_dir is None:
        # Default to the src directory
        src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    src_path = Path(src_dir)
    return str(src_path / file_path)


def get_ip_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def get_wifi_name():
    try:
        output = subprocess.check_output(["iwgetid", "-r"]).decode("utf-8").strip()
        return output
    except subprocess.CalledProcessError:
        return None


def is_connected():
    """Check if the Raspberry Pi has an internet connection."""
    try:
        # Try to connect to Google's public DNS server
        conn = socket.create_connection(("8.8.8.8", 53), timeout=2)
    except OSError:
        return False
    else:
        try:
            conn.close()
        except Exception:
            pass
        return True


def get_font(
    font_name, font_size=50, font_weight="normal", *, strict=False
):
    """Return a PIL ImageFont for the requested font.

    If ``strict`` is ``True`` an exception will be raised when the font or
    weight cannot be resolved.  Otherwise a warning is logged and ``None`` is
    returned.  This behaviour preserves the previous API while allowing callers
    to opt in to stricter error handling.
    """

    if font_name not in FONT_FAMILIES:
        message = f"Requested font not found: font_name={font_name}"
        if strict:
            raise ValueError(message)
        logger.warning(message)
        return None

    font_variants = FONT_FAMILIES[font_name]

    font_entry = next(
        (entry for entry in font_variants if entry["font-weight"] == font_weight),
        None,
    )
    if font_entry is None:
        font_entry = font_variants[0]  # Default to first available variant

    if font_entry:
        font_path = resolve_path(os.path.join("static", "fonts", font_entry["file"]))
        return ImageFont.truetype(font_path, font_size)

    message = (
        f"Requested font weight not found: font_name={font_name}, font_weight={font_weight}"
    )
    if strict:
        raise ValueError(message)
    logger.warning(message)
    return None


def get_fonts():
    fonts_list = []
    for font_family, variants in FONT_FAMILIES.items():
        for variant in variants:
            fonts_list.append(
                {
                    "font_family": font_family,
                    "url": resolve_path(
                        os.path.join("static", "fonts", variant["file"])
                    ),
                    "font_weight": variant.get("font-weight", "normal"),
                    "font_style": variant.get("font-style", "normal"),
                }
            )
    return fonts_list


def get_font_path(font_name):
    return resolve_path(os.path.join("static", "fonts", FONTS[font_name]))


def generate_startup_image(dimensions=(800, 480)):
    bg_color = (255, 255, 255)
    text_color = (0, 0, 0)
    width, height = dimensions

    hostname = socket.gethostname()

    image = Image.new("RGBA", dimensions, bg_color)
    image_draw = ImageDraw.Draw(image)

    title_font_size = width * 0.145
    title_font = get_font("Jost", title_font_size)
    if title_font is None:
        logger.warning("Falling back to default font for startup title")
        try:
            title_font = ImageFont.load_default()
        except Exception as exc:
            raise RuntimeError("Unable to load a font for startup title") from exc
    image_draw.text(
        (width / 2, height / 2),
        "inkypi",
        anchor="mm",
        fill=text_color,
        font=title_font,
    )

    text = f"To get started, visit http://{hostname}.local"
    text_font_size = width * 0.032
    text_font = get_font("Jost", text_font_size)
    if text_font is None:
        logger.warning("Falling back to default font for startup message")
        try:
            text_font = ImageFont.load_default()
        except Exception as exc:
            raise RuntimeError("Unable to load a font for startup message") from exc
    image_draw.text(
        (width / 2, height * 3 / 4),
        text,
        anchor="mm",
        fill=text_color,
        font=text_font,
    )

    return image


def parse_form(request_form):
    request_dict = request_form.to_dict()
    for key in request_form.keys():
        if key.endswith("[]"):
            request_dict[key] = request_form.getlist(key)
    return request_dict


def handle_request_files(request_files, form_data=None):
    if form_data is None:
        form_data = {}
    allowed_file_extensions = {"png", "jpg", "jpeg", "gif", "webp"}
    file_location_map = {}
    # handle existing file locations being provided as part of the form data
    # Some request file objects (e.g., test doubles) may not implement .keys().
    try:
        rf_keys = set(request_files.keys())
    except Exception:
        # Derive keys from items() as a fallback
        try:
            rf_keys = {k for (k, _v) in request_files.items(multi=True)}
        except Exception:
            try:
                rf_keys = {k for (k, _v) in request_files.items()}
            except Exception:
                rf_keys = set()

    for key in rf_keys:
        is_list = key.endswith("[]")
        if key in form_data:
            # Prefer getlist if available; otherwise fall back to standard dict access
            if is_list and hasattr(form_data, "getlist"):
                file_location_map[key] = form_data.getlist(key)
            else:
                file_location_map[key] = form_data.get(key)
    # add new files in the request
    for key, file in request_files.items(multi=True):
        is_list = key.endswith("[]")
        file_name = file.filename
        if not file_name:
            continue

        extension = os.path.splitext(file_name)[1].replace(".", "")
        if not extension or extension.lower() not in allowed_file_extensions:
            # Skip non-image uploads
            continue

        file_name = os.path.basename(file_name)

        file_save_dir = resolve_path(os.path.join("static", "images", "saved"))
        # Ensure the output directory exists
        os.makedirs(file_save_dir, exist_ok=True)
        file_path = os.path.join(file_save_dir, file_name)

        # Enforce maximum upload size (bytes). Default 10 MB; override with env MAX_UPLOAD_BYTES
        try:
            max_upload_bytes_env = os.getenv("MAX_UPLOAD_BYTES")
            max_upload_bytes = (
                int(max_upload_bytes_env) if max_upload_bytes_env else 10 * 1024 * 1024
            )
        except Exception:
            max_upload_bytes = 10 * 1024 * 1024

        # Read file content to validate type and size safely
        try:
            # Read all bytes and reset pointer if needed
            file_stream_pos = None
            try:
                file_stream_pos = file.stream.tell()
            except Exception:
                pass

            content = file.read()
            # Reset stream so Flask/Werkzeug isn't confused later
            try:
                if file_stream_pos is not None:
                    file.stream.seek(file_stream_pos)
                else:
                    file.seek(0)
            except Exception:
                pass

            if content is None:
                raise RuntimeError("Empty upload content")

            if len(content) > max_upload_bytes:
                raise RuntimeError(
                    f"Uploaded file exceeds size limit of {max_upload_bytes} bytes"
                )

            # Validate that the file is a decodable image
            bio = BytesIO(content)
            try:
                with Image.open(bio) as img_verify:
                    img_verify.verify()  # Verify header/decoder
            except Exception as e:
                raise RuntimeError(f"Invalid image upload: {e}")

            # Re-open with standardized helper to apply orientation and save
            img = load_image_from_bytes(content, image_open=Image.open)
            if img is None:
                raise RuntimeError("Failed to open image for processing")
            img = ImageOps.exif_transpose(img)
            if img is None:
                raise RuntimeError("Failed to transpose image for processing")
            img.save(file_path)
        except Exception as e:
            # Fail hard on invalid image data
            logger.error(f"Failed to process uploaded file '{file_name}': {e}")
            raise

        if is_list:
            file_location_map.setdefault(key, [])
            file_location_map[key].append(file_path)
        else:
            file_location_map[key] = file_path
    return file_location_map

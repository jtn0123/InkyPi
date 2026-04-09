import logging
import os
import shutil
import socket
import subprocess
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

# Google's public DNS server — used for local IP detection (UDP connect,
# no data sent) and TCP connectivity checks. Not a security-sensitive endpoint.
_DNS_CHECK_HOST = "8.8.8.8"  # NOSONAR — connectivity check, not security-sensitive

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
    "ds-digi": "DS-DIGI.TTF",
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
            s.connect((_DNS_CHECK_HOST, 80))
            return s.getsockname()[0]
    except OSError:
        return None


def get_wifi_name():
    try:
        iwgetid_bin = shutil.which("iwgetid") or "/sbin/iwgetid"
        if not os.path.isabs(iwgetid_bin):
            return None
        output = subprocess.check_output([iwgetid_bin, "-r"]).decode("utf-8").strip()
        return output
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def is_connected():
    """Check if the Raspberry Pi has an internet connection."""
    sock = None
    try:
        sock = socket.create_connection((_DNS_CHECK_HOST, 53), timeout=2)
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def get_font(font_name, font_size=50, font_weight="normal", strict=False):
    font_variants = FONT_FAMILIES.get(font_name)
    if not font_variants:
        logger.warning(f"Requested font not found: font_name={font_name}")
    else:
        font_entry = next(
            (entry for entry in font_variants if entry["font-weight"] == font_weight),
            None,
        )
        if font_entry is None:
            font_entry = font_variants[0]  # Default to first available variant
        font_path = resolve_path(os.path.join("static", "fonts", font_entry["file"]))
        return ImageFont.truetype(font_path, font_size)

    if strict:
        raise ValueError(
            f"Requested font not available: font_name={font_name}, font_weight={font_weight}"
        )
    return None


def get_fonts():
    fonts_list = [
        {
            "font_family": font_family,
            "url": resolve_path(os.path.join("static", "fonts", variant["file"])),
            "font_weight": variant.get("font-weight", "normal"),
            "font_style": variant.get("font-style", "normal"),
        }
        for font_family, variants in FONT_FAMILIES.items()
        for variant in variants
    ]
    return fonts_list


def get_font_path(font_name):
    return resolve_path(os.path.join("static", "fonts", FONTS[font_name]))


def generate_startup_image(dimensions=(800, 480)):
    bg_color = (255, 255, 255)
    text_color = (0, 0, 0)
    width, height = dimensions

    hostname = socket.gethostname()
    ip = get_ip_address()

    image = Image.new("RGBA", dimensions, bg_color)
    image_draw = ImageDraw.Draw(image)

    title_font_size = width * 0.145
    image_draw.text(
        (width / 2, height / 2),
        "inkypi",
        anchor="mm",
        fill=text_color,
        font=get_font("Jost", title_font_size),
    )

    text = f"To get started, visit http://{hostname}.local"
    text_font_size = width * 0.032

    # Draw the instructions
    y_text = height * 3 / 4
    image_draw.text(
        (width / 2, y_text),
        text,
        anchor="mm",
        fill=text_color,
        font=get_font("Jost", text_font_size),
    )

    # Draw the IP on a line below
    ip_text_font_size = width * 0.032
    if ip:
        ip_text = f"or http://{ip}"
        bbox = image_draw.textbbox((0, 0), text, font=get_font("Jost", text_font_size))
        text_height = bbox[3] - bbox[1]
        ip_y = y_text + text_height * 1.35
        image_draw.text(
            (width / 2, ip_y),
            ip_text,
            anchor="mm",
            fill=text_color,
            font=get_font("Jost", ip_text_font_size),
        )

    return image


def parse_form(request_form):
    request_dict = request_form.to_dict()
    for key in request_form:
        if key.endswith("[]"):
            request_dict[key] = request_form.getlist(key)
    return request_dict


def _process_uploaded_file(extension: str, file_path: str, content: bytes) -> None:
    """Persist an uploaded file, applying type-specific validation.

    - PDFs are written as-is.
    - JPEG files are EXIF-transposed before saving.
    - All other images are verified by the decoder before writing.

    Raises RuntimeError on invalid image content.
    """
    if extension == "pdf":
        with open(file_path, "wb") as out:
            out.write(content)
    elif extension in {"jpg", "jpeg"}:
        try:
            with Image.open(BytesIO(content)) as img:
                img = ImageOps.exif_transpose(img)
                img.save(file_path)
        except (OSError, ValueError) as e:
            raise RuntimeError("Invalid image upload") from e
    else:
        # Verify decoder can read it before persisting.
        try:
            with Image.open(BytesIO(content)) as img_verify:
                img_verify.verify()
        except (OSError, ValueError) as e:
            raise RuntimeError("Invalid image upload") from e
        with open(file_path, "wb") as out:
            out.write(content)


_ALLOWED_FILE_EXTENSIONS = {
    "pdf",
    "png",
    "avif",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "heif",
    "heic",
}

# Magic-byte signatures for image formats.  Each entry maps a normalised
# extension (or set of equivalent extensions) to a list of byte-prefix
# tuples that are valid for that format.  Only image extensions are listed
# here; PDF is validated separately by downstream code.
_IMAGE_MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],  # Full check: bytes[8:12] == b"WEBP" – done in validator
    "bmp": [b"BM"],
    # HEIF/HEIC/AVIF use ISO Base Media File Format; magic is at offset 4.
    # We allow any ftyp box (offset 4–8 == b"ftyp") rather than enumerating
    # every brand, then rely on PIL.verify() for deeper validation.
    "heif": [],  # checked via PIL only
    "heic": [],  # checked via PIL only
    "avif": [],  # checked via PIL only
}

# Image extensions that require PIL verification after the magic-byte check.
_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    ext for ext in _ALLOWED_FILE_EXTENSIONS if ext != "pdf"
)


def _check_magic_bytes(content: bytes, extension: str) -> bool:
    """Return True if *content* starts with a recognised magic signature for *extension*.

    For formats without a simple prefix (heif/heic/avif) we defer entirely to
    PIL.verify() and return True here so the caller proceeds to that check.

    For WebP we additionally verify the "WEBP" brand at offset 8.
    """
    sigs = _IMAGE_MAGIC_SIGNATURES.get(extension)
    if sigs is None:
        # Unknown image extension — allow PIL to decide.
        return True
    if not sigs:
        # Formats delegated entirely to PIL (heif/heic/avif).
        return True
    if not any(content.startswith(sig) for sig in sigs):
        return False
    # Extra check for WebP: the 4-byte brand field at offset 8 must be b"WEBP".
    if extension == "webp":
        return content[8:12] == b"WEBP"
    return True


def _validate_image_content(content: bytes, extension: str) -> None:
    """Validate image content using magic bytes and PIL verification.

    Raises ``RuntimeError`` with a user-safe message when the file is not a
    valid image.  The caller is responsible for ensuring *content* is non-empty
    before calling this function.
    """
    if not _check_magic_bytes(content, extension):
        raise RuntimeError("Uploaded file is not a valid image")

    # PIL verification: catches malformed files that pass the magic-byte check.
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
    except Exception as exc:
        raise RuntimeError("Uploaded file is not a valid image") from exc


def _get_existing_file_location(key, form_data):
    """Return the existing file location(s) from form_data for the given key.

    Returns the stored value for scalar keys, or a list for list keys (``key[]``).
    Returns None if the key is not present in form_data.
    """
    if key not in form_data:
        return None, False
    is_list = key.endswith("[]")
    if not is_list:
        return form_data.get(key), True
    if hasattr(form_data, "getlist"):
        return form_data.getlist(key), True
    existing = form_data.get(key)
    return (existing if isinstance(existing, list) else [existing]), True


def _validate_and_read_file(file, file_name):
    """Read and validate file content. Returns (content, extension) or raises RuntimeError."""
    extension = os.path.splitext(file_name)[1].replace(".", "")
    if not extension or extension.lower() not in _ALLOWED_FILE_EXTENSIONS:
        return None, None

    ext = extension.lower()

    content = file.read()
    if content is None:
        raise RuntimeError("Empty upload content")

    if len(content) == 0:
        raise RuntimeError("Uploaded file is not a valid image")

    max_upload_bytes_env = os.getenv("MAX_UPLOAD_BYTES")
    max_upload_bytes = (
        int(max_upload_bytes_env) if max_upload_bytes_env else 10 * 1024 * 1024
    )
    if len(content) > max_upload_bytes:
        raise RuntimeError(
            f"Uploaded file exceeds size limit of {max_upload_bytes} bytes"
        )

    # Validate magic bytes and PIL integrity for image uploads.
    # PDFs are handled by downstream code; skip magic-byte check for them.
    if ext in _IMAGE_EXTENSIONS:
        _validate_image_content(content, ext)

    return content, ext


def _rewind_file_stream(file):
    """Rewind file stream so callers can re-read from the beginning."""
    try:
        if hasattr(file, "stream"):
            file.stream.seek(0)
        elif hasattr(file, "seek"):
            file.seek(0)
    except (OSError, AttributeError):
        logger.debug("Failed to rewind file stream", exc_info=True)


def _save_uploaded_file(file, file_name, extension, content):
    """Persist the uploaded file and return its path on disk."""
    safe_name = os.path.basename(file_name)
    file_save_dir = resolve_path(os.path.join("static", "images", "saved"))
    os.makedirs(file_save_dir, exist_ok=True)
    # Prefix with timestamp to avoid silent overwrites from duplicate filenames
    unique_name = f"{int(time.time())}_{safe_name}"
    file_path = os.path.join(file_save_dir, unique_name)
    _rewind_file_stream(file)
    _process_uploaded_file(extension, file_path, content)
    return file_path


def _collect_existing_locations(request_keys, form_data):
    """Seed the file-location map with any pre-existing paths from form_data."""
    file_location_map = {}
    for key in request_keys:
        value, found = _get_existing_file_location(key, form_data)
        if found:
            file_location_map[key] = value
    return file_location_map


def handle_request_files(request_files, form_data=None):
    if form_data is None:
        form_data = {}
    request_keys = (
        set(request_files.keys()) if hasattr(request_files, "keys") else set()
    )
    # Seed map with existing file locations from form data
    file_location_map = _collect_existing_locations(request_keys, form_data)

    # Add new files from the request
    for key, file in request_files.items(multi=True):
        file_name = file.filename
        if not file_name:
            continue

        content, extension = _validate_and_read_file(file, file_name)
        if content is None:
            continue

        file_path = _save_uploaded_file(file, file_name, extension, content)

        if key.endswith("[]"):
            file_location_map.setdefault(key, [])
            file_location_map[key].append(file_path)
        else:
            file_location_map[key] = file_path
    return file_location_map

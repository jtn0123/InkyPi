import logging
import os
import shutil
import socket
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

FONT_FAMILIES = {
    "Dogica": [{
        "font-weight": "normal",
        "file": "dogicapixel.ttf"
    },{
        "font-weight": "bold",
        "file": "dogicapixelbold.ttf"
    }],
    "Jost": [{
        "font-weight": "normal",
        "file": "Jost.ttf"
    },{
        "font-weight": "bold",
        "file": "Jost-SemiBold.ttf"
    }],
    "Napoli": [{
        "font-weight": "normal",
        "file": "Napoli.ttf"
    }],
    "DS-Digital": [{
        "font-weight": "normal",
        "file": os.path.join("DS-DIGI", "DS-DIGI.TTF")
    }]
}

FONTS = {
    "ds-digi": "DS-DIGI.TTF",
    "napoli": "Napoli.ttf",
    "jost": "Jost.ttf",
    "jost-semibold": "Jost-SemiBold.ttf"
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
        iwgetid_bin = shutil.which("iwgetid") or "/sbin/iwgetid"
        if not os.path.isabs(iwgetid_bin):
            return None
        output = subprocess.check_output([iwgetid_bin, '-r']).decode('utf-8').strip()
        return output
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def is_connected():
    """Check if the Raspberry Pi has an internet connection."""
    sock = None
    try:
        # Try to connect to Google's public DNS server
        sock = socket.create_connection(("8.8.8.8", 53), timeout=2)
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
    fonts_list = []
    for font_family, variants in FONT_FAMILIES.items():
        for variant in variants:
            fonts_list.append({
                "font_family": font_family,
                "url": resolve_path(os.path.join("static", "fonts", variant["file"])),
                "font_weight": variant.get("font-weight", "normal"),
                "font_style": variant.get("font-style", "normal"),
            })
    return fonts_list

def get_font_path(font_name):
    return resolve_path(os.path.join("static", "fonts", FONTS[font_name]))

def generate_startup_image(dimensions=(800,480)):
    bg_color = (255,255,255)
    text_color = (0,0,0)
    width, height = dimensions

    hostname = socket.gethostname()
    ip = get_ip_address()

    image = Image.new("RGBA", dimensions, bg_color)
    image_draw = ImageDraw.Draw(image)

    title_font_size = width * 0.145
    image_draw.text((width/2, height/2), "inkypi", anchor="mm", fill=text_color, font=get_font("Jost", title_font_size))

    text = f"To get started, visit http://{hostname}.local"
    text_font_size = width * 0.032

    # Draw the instructions
    y_text = height * 3 / 4
    image_draw.text((width/2, y_text), text, anchor="mm", fill=text_color, font=get_font("Jost", text_font_size))

    # Draw the IP on a line below
    ip_text_font_size = width * 0.032
    if ip:
        ip_text = f"or http://{ip}"
        bbox = image_draw.textbbox((0, 0), text, font=get_font("Jost", text_font_size))
        text_height = bbox[3] - bbox[1]
        ip_y = y_text + text_height * 1.35
        image_draw.text((width/2, ip_y), ip_text, anchor="mm", fill=text_color, font=get_font("Jost", ip_text_font_size))

    return image

def parse_form(request_form):
    request_dict = request_form.to_dict()
    for key in request_form.keys():
        if key.endswith('[]'):
            request_dict[key] = request_form.getlist(key)
    return request_dict

def handle_request_files(request_files, form_data=None):
    if form_data is None:
        form_data = {}
    allowed_file_extensions = {'pdf', 'png', 'avif', 'jpg', 'jpeg', 'gif', 'webp', 'heif', 'heic'}
    file_location_map = {}
    request_keys = set(request_files.keys()) if hasattr(request_files, "keys") else set()
    # handle existing file locations being provided as part of the form data
    for key in request_keys:
        is_list = key.endswith('[]')
        if key in form_data:
            if is_list:
                if hasattr(form_data, "getlist"):
                    file_location_map[key] = form_data.getlist(key)
                else:
                    existing = form_data.get(key)
                    file_location_map[key] = existing if isinstance(existing, list) else [existing]
            else:
                file_location_map[key] = form_data.get(key)
    # add new files in the request
    for key, file in request_files.items(multi=True):
        is_list = key.endswith('[]')
        file_name = file.filename
        if not file_name:
            continue

        extension = os.path.splitext(file_name)[1].replace('.', '')
        if not extension or extension.lower() not in allowed_file_extensions:
            continue

        file_name = os.path.basename(file_name)

        file_save_dir = resolve_path(os.path.join("static", "images", "saved"))
        os.makedirs(file_save_dir, exist_ok=True)
        # Prefix with timestamp to avoid silent overwrites from duplicate filenames
        import time
        unique_name = f"{int(time.time())}_{file_name}"
        file_path = os.path.join(file_save_dir, unique_name)

        # Read raw bytes once so this works with both FileStorage and test fakes.
        content = file.read()
        if content is None:
            raise RuntimeError("Empty upload content")

        max_upload_bytes_env = os.getenv("MAX_UPLOAD_BYTES")
        max_upload_bytes = int(max_upload_bytes_env) if max_upload_bytes_env else 10 * 1024 * 1024
        if len(content) > max_upload_bytes:
            raise RuntimeError(f"Uploaded file exceeds size limit of {max_upload_bytes} bytes")

        # Rewind file objects for callers that expect stream position to remain usable.
        try:
            if hasattr(file, "stream"):
                file.stream.seek(0)
            elif hasattr(file, "seek"):
                file.seek(0)
        except Exception:
            logger.debug("Failed to rewind file stream", exc_info=True)

        # Save PDFs as-is. Validate and save images.
        if extension == "pdf":
            with open(file_path, "wb") as out:
                out.write(content)
        elif extension in {'jpg', 'jpeg'}:
            try:
                with Image.open(BytesIO(content)) as img:
                    img = ImageOps.exif_transpose(img)
                    img.save(file_path)
            except Exception as e:
                raise RuntimeError("Invalid image upload") from e
        else:
            # Verify decoder can read it before persisting.
            try:
                with Image.open(BytesIO(content)) as img_verify:
                    img_verify.verify()
            except Exception as e:
                raise RuntimeError("Invalid image upload") from e
            with open(file_path, "wb") as out:
                out.write(content)

        if is_list:
            file_location_map.setdefault(key, [])
            file_location_map[key].append(file_path)
        else:
            file_location_map[key] = file_path
    return file_location_map

import hashlib
import logging
import os
import subprocess
import tempfile
from io import BytesIO

import requests
from PIL import Image, ImageEnhance
from PIL.Image import Resampling

LANCZOS = Resampling.LANCZOS

logger = logging.getLogger(__name__)

def get_image(image_url, timeout_seconds: float = 10.0):
    try:
        response = requests.get(image_url, timeout=timeout_seconds)
    except TypeError:
        # Some tests monkeypatch requests.get without supporting timeout
        try:
            response = requests.get(image_url)
        except Exception as e:
            logger.error(f"Failed to fetch image from {image_url}: {str(e)}")
            return None
    except Exception as e:
        logger.error(f"Failed to fetch image from {image_url}: {str(e)}")
        return None

    img = None
    if 200 <= response.status_code < 300 or response.status_code == 304:
        # Ensure PIL image file resources are cleaned up by copying from a context-managed open
        try:
            with Image.open(BytesIO(response.content)) as _img:
                img = _img.copy()
        except Exception as e:
            logger.error(f"Failed to decode image from {image_url}: {str(e)}")
            img = None
    else:
        logger.error(f"Received non-200 response from {image_url}: status_code: {response.status_code}")
    return img

def change_orientation(image, orientation, inverted=False):
    if orientation == 'horizontal':
        angle = 0
    elif orientation == 'vertical':
        angle = 90

    if inverted:
        angle = (angle + 180) % 360

    return image.rotate(angle, expand=1)

def resize_image(image, desired_size, image_settings=None):
    img_width, img_height = image.size
    desired_width, desired_height = desired_size
    desired_width, desired_height = int(desired_width), int(desired_height)

    img_ratio = img_width / img_height
    desired_ratio = desired_width / desired_height

    if image_settings is None:
        image_settings = []
    keep_width = "keep-width" in image_settings

    x_offset, y_offset = 0,0
    new_width, new_height = img_width,img_height
    # Step 1: Determine crop dimensions
    desired_ratio = desired_width / desired_height
    if img_ratio > desired_ratio:
        # Image is wider than desired aspect ratio
        new_width = int(img_height * desired_ratio)
        if not keep_width:
            x_offset = (img_width - new_width) // 2
    else:
        # Image is taller than desired aspect ratio
        new_height = int(img_width / desired_ratio)
        if not keep_width:
            y_offset = (img_height - new_height) // 2

    # Step 2: Crop the image
    image = image.crop((x_offset, y_offset, x_offset + new_width, y_offset + new_height))

    # Step 3: Resize to the exact desired dimensions (if necessary)
    return image.resize((desired_width, desired_height), LANCZOS)

def apply_image_enhancement(img, image_settings=None):

    if image_settings is None:
        image_settings = {}

    # Apply Brightness
    img = ImageEnhance.Brightness(img).enhance(image_settings.get("brightness", 1.0))

    # Apply Contrast
    img = ImageEnhance.Contrast(img).enhance(image_settings.get("contrast", 1.0))

    # Apply Saturation (Color)
    img = ImageEnhance.Color(img).enhance(image_settings.get("saturation", 1.0))

    # Apply Sharpness
    img = ImageEnhance.Sharpness(img).enhance(image_settings.get("sharpness", 1.0))

    return img

def compute_image_hash(image):
    """Compute SHA-256 hash of an image.

    Raises:
        ValueError: If image is None.
    """
    if image is None:
        raise ValueError("compute_image_hash called with None image")
    image = image.convert("RGB")
    img_bytes = image.tobytes()
    return hashlib.sha256(img_bytes).hexdigest()

def take_screenshot_html(html_str, dimensions, timeout_ms=None):
    image = None
    html_file_path = None
    try:
        # Create a temporary HTML file
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
            html_file.write(html_str.encode("utf-8"))
            html_file_path = html_file.name

        image = take_screenshot(html_file_path, dimensions, timeout_ms)
    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
    finally:
        if html_file_path and os.path.exists(html_file_path):
            try:
                os.remove(html_file_path)
            except Exception:
                pass

    return image

def take_screenshot(target, dimensions, timeout_ms=None):
    image = None
    img_file_path = None
    try:
        # Create a temporary output file for the screenshot
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
            img_file_path = img_file.name

        # Try different browser binaries in order of preference
        browsers = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "chromium",
            "chromium-headless-shell",
            "google-chrome"
        ]

        command = None
        for browser in browsers:
            if os.path.exists(browser) or (browser in ["chromium", "chromium-headless-shell", "google-chrome"] and subprocess.run(["which", browser], capture_output=True).returncode == 0):
                command = [
                    browser,
                    target,
                    "--headless",
                    f"--screenshot={img_file_path}",
                    f"--window-size={dimensions[0]},{dimensions[1]}",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--use-gl=swiftshader",
                    "--hide-scrollbars",
                    "--in-process-gpu",
                    "--js-flags=--jitless",
                    "--disable-zero-copy",
                    "--disable-gpu-memory-buffer-compositor-resources",
                    "--disable-extensions",
                    "--disable-plugins",
                    "--mute-audio",
                    "--no-sandbox"
                ]
                if timeout_ms:
                    command.append(f"--timeout={timeout_ms}")
                break

        if command is None:
            logger.error("Failed to take screenshot: No supported browser found. Install Chromium or Google Chrome.")
            return None

        try:
            result = subprocess.run(command, capture_output=True)
        except FileNotFoundError:
            logger.error("Failed to take screenshot: Browser binary not found.")
            return None

        # Check if the process failed or the output file is missing
        if result.returncode != 0 or not (img_file_path and os.path.exists(img_file_path)):
            logger.error("Failed to take screenshot:")
            try:
                logger.error(result.stderr.decode('utf-8'))
            except Exception:
                pass
            return None

        # Load the image using PIL
        with Image.open(img_file_path) as img:
            image = img.copy()

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
    finally:
        if img_file_path and os.path.exists(img_file_path):
            try:
                os.remove(img_file_path)
            except Exception:
                pass

    return image

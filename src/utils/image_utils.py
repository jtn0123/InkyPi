import hashlib
import logging
import os
import shutil
import subprocess
import shutil

logger = logging.getLogger(__name__)

def get_image(image_url):
    response = requests.get(image_url, timeout=30)
    img = None
    if 200 <= response.status_code < 300 or response.status_code == 304:
        # Use standardized loader
        img = load_image_from_bytes(response.content)
        if img is None:
            logger.error(f"Failed to decode image from {image_url}")
    else:
        logger.error(
            f"Received non-200 response from {image_url}: status_code: {response.status_code}"
        )
    return img


def change_orientation(image, orientation, inverted: bool = False):
    """Rotate an image based on the given orientation.

    Raises a :class:`ValueError` if an unsupported orientation is provided.
    """
    if orientation == "horizontal":
        angle = 0
    elif orientation == "vertical":
        angle = 90
    else:
        raise ValueError(f"Unsupported orientation: {orientation}")

    if inverted:
        angle = (angle + 180) % 360

    return image.rotate(angle, expand=1)


def resize_image(image, desired_size, image_settings=None):
    img_width, img_height = image.size
    desired_width, desired_height = desired_size
    desired_width, desired_height = int(desired_width), int(desired_height)

    if img_height == 0:
        raise ValueError("Image height must be non-zero")
    if desired_height == 0:
        raise ValueError("Desired height must be non-zero")

    img_ratio = img_width / img_height
    desired_ratio = desired_width / desired_height

    if image_settings is None:
        image_settings = []
    keep_width = "keep-width" in image_settings

    x_offset, y_offset = 0, 0
    new_width, new_height = img_width, img_height
    # Step 1: Determine crop dimensions
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
    image = image.crop(
        (x_offset, y_offset, x_offset + new_width, y_offset + new_height)
    )

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
    """Compute SHA-256 hash of an image."""
    image = image.convert("RGB")
    img_bytes = image.tobytes()
    return hashlib.sha256(img_bytes).hexdigest()

def take_screenshot_html(html_str, dimensions, timeout_ms=None):
    image = None
    try:
        # Create a temporary HTML file
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
            html_file.write(html_str.encode("utf-8"))
            html_file_path = html_file.name

        image = take_screenshot(html_file_path, dimensions, timeout_ms)

        # Remove html file
        os.remove(html_file_path)

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")

    return image

def _find_chromium_binary():
    """Find the first available Chromium-based binary in system PATH."""
    candidates = ["chromium-headless-shell", "chromium", "chrome"]
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            logger.debug(f"Found browser binary: {candidate} at {path}")
            return candidate
    return None


def take_screenshot(target, dimensions, timeout_ms=None):
    image = None
    try:
        # Find available browser binary
        browser = _find_chromium_binary()
        if not browser:
            logger.error("No Chromium-based browser found. Install chromium, chromium-headless-shell, or chrome.")
            return None

        # Create a temporary output file for the screenshot
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
            img_file_path = img_file.name

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
            "--renderer-process-limit=1",
            "--no-zygote",
            "--no-sandbox"
        ]
        if timeout_ms:
            command.append(f"--timeout={timeout_ms}")
        result = subprocess.run(command, capture_output=True, check=False)

        # Check if the process failed or the output file is missing
        if result.returncode != 0 or not os.path.exists(img_file_path):
            logger.error(f"Failed to take screenshot (return code: {result.returncode})")
            return None

        # Load the image using PIL
        with Image.open(img_file_path) as img:
            image = img.copy()

        # Remove image files
        os.remove(img_file_path)

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")

    return image

def pad_image_blur(img: Image, dimensions: tuple[int, int]) -> Image:
    bkg = ImageOps.fit(img, dimensions)
    bkg = bkg.filter(ImageFilter.BoxBlur(8))
    img = ImageOps.contain(img, dimensions)

    img_size = img.size
    bkg.paste(img, ((dimensions[0] - img_size[0]) // 2, (dimensions[1] - img_size[1]) // 2))
    return bkg


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


def _playwright_screenshot_html(
    html_file_path: str, dimensions: tuple[int, int]
) -> Image.Image | None:
    """Try to render a local HTML file using Playwright (if available)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    img: Image.Image | None = None
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    args=[
                        "--allow-file-access-from-files",
                        "--enable-local-file-accesses",
                        "--disable-web-security",
                    ]
                )
            except Exception:
                return None
            try:
                page = browser.new_page(
                    viewport={"width": int(dimensions[0]), "height": int(dimensions[1])}
                )
                page.goto(f"file://{html_file_path}")
                # Wait for network to be idle-ish
                try:
                    page.wait_for_load_state("load", timeout=4000)
                    # Ensure <img> resources finished (including file://)
                    page.evaluate(
                        "() => Promise.all(Array.from(document.images).map(img => img.complete ? Promise.resolve() : new Promise(r => { img.onload = () => r(); img.onerror = () => r(); })))"
                    )
                except Exception:
                    pass
                png_bytes = page.screenshot(
                    clip={
                        "x": 0,
                        "y": 0,
                        "width": int(dimensions[0]),
                        "height": int(dimensions[1]),
                    }
                )
                img = load_image_from_bytes(png_bytes)
            finally:
                browser.close()
    except Exception:
        return None
    return img


def take_screenshot_html(html_str, dimensions, timeout_ms=None):
    image = None
    html_file_path = None
    try:
        # Create a temporary HTML file
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
            html_file.write(html_str.encode("utf-8"))
            html_file_path = html_file.name

        # Load via file:// scheme so linked local assets (CSS, fonts, images)
        # are treated as same-origin file resources in headless Chrome.
        # Prefer Playwright if available; it tends to load local assets more reliably
        image = _playwright_screenshot_html(html_file_path, dimensions)
        if image is None:
            image = take_screenshot(f"file://{html_file_path}", dimensions, timeout_ms)
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
            "google-chrome",
        ]

        command = None
        for browser in browsers:
            if os.path.exists(browser) or shutil.which(browser):
                command = [
                    browser,
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
                    "--no-sandbox",
                    # Allow loading local file-based resources referenced by templates
                    "--allow-file-access-from-files",
                    "--enable-local-file-accesses",
                    # Relax same-origin so file:// linked assets load predictably
                    "--disable-web-security",
                    target,
                ]
                if timeout_ms:
                    command.append(f"--timeout={timeout_ms}")
                break

        if command is None:
            logger.error(
                "Failed to take screenshot: No supported browser found. Install Chromium or Google Chrome."
            )
            return None

        timeout_seconds = (timeout_ms / 1000) if timeout_ms else None

        try:
            result = subprocess.run(
                command, capture_output=True, timeout=timeout_seconds
            )
        except FileNotFoundError:
            logger.error("Failed to take screenshot: Browser binary not found.")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Failed to take screenshot: Browser process timed out.")
            return None

        # Check if the process failed or the output file is missing
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            logger.error(
                f"Failed to take screenshot (exit code {result.returncode}): {stderr}"
            )
            return None
        if not (img_file_path and os.path.exists(img_file_path)):
            logger.error("Failed to take screenshot: screenshot file not found")
            return None

        # Load the image using standardized helper
        image = load_image_from_path(img_file_path)
        if image is None:
            logger.error("Failed to load screenshot image from temp file")
            return None

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
    finally:
        if img_file_path and os.path.exists(img_file_path):
            try:
                os.remove(img_file_path)
            except Exception:
                pass

    return image

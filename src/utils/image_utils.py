import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from io import BytesIO
from typing import Any

from PIL import Image
from PIL.Image import Resampling

from utils.http_utils import http_get, pinned_dns
from utils.security_utils import validate_url_with_ips

# ImageEnhance / ImageFilter / ImageOps are imported lazily from the
# functions that use them (JTN-606).  Keeping them at module scope inflated
# startup RSS by ~8 MB on Pi Zero 2 W because every import of image_utils
# pulled them in — even for pure hashing callers that never touch them.

LANCZOS = Resampling.LANCZOS

logger = logging.getLogger(__name__)

# Default and maximum timeout for browser subprocess screenshots (seconds).
_DEFAULT_SCREENSHOT_TIMEOUT_S = 30
_MAX_SCREENSHOT_TIMEOUT_S = 60

# Common prefix for all screenshot failure log messages.
_SCREENSHOT_ERROR_PREFIX = "Failed to take screenshot:"


def load_image_from_bytes(
    content: bytes, image_open: Callable[[Any], Image.Image] | None = None
) -> Image.Image | None:
    """Safely load an image from raw bytes and return a detached copy.

    Uses a context-managed open to ensure decoder resources are released,
    returning a fully materialized copy of the image.
    """
    try:
        opener = image_open or Image.open
        with opener(BytesIO(content)) as _img:
            img: Image.Image = _img
            return img.copy()
    except (OSError, ValueError) as e:
        logger.error(f"Failed to decode image from bytes: {e}")
        return None


def process_image_from_bytes(
    content: bytes,
    processor: Callable[[Image.Image], Image.Image | None],
    image_open: Callable[[Any], Image.Image] | None = None,
) -> Image.Image | None:
    """Open an image from bytes and process it within a managed context.

    This avoids holding the underlying stream open after processing without
    forcing a copy of the original image. Returns the processor's result or
    None on failure.
    """
    try:
        opener = image_open or Image.open
        with opener(BytesIO(content)) as _img:
            return processor(_img)
    except (OSError, ValueError, TypeError) as e:
        logger.error(f"Failed to process image from bytes: {e}")
        return None


def load_image_from_path(
    path: str, image_open: Callable[[str], Image.Image] | None = None
) -> Image.Image | None:
    """Safely load an image from a filesystem path and return a detached copy."""
    try:
        opener = image_open or Image.open
        with opener(path) as _img:
            img: Image.Image = _img
            return img.copy()
    except (OSError, ValueError) as e:
        logger.error(f"Failed to open image file '{path}': {e}")
        return None


def get_image(image_url, timeout_seconds: float = 10.0):
    """Fetch an image from a URL and return a PIL Image, or None on failure.

    The hostname is validated and DNS-pinned for the duration of the fetch
    to mitigate DNS-rebinding SSRF (JTN-656).

    Args:
        image_url: The URL of the image to fetch.
        timeout_seconds: Request timeout in seconds (default 10).

    Returns:
        A ``PIL.Image.Image`` on success, or ``None`` if the request fails or
        the response body cannot be decoded as an image.
    """
    try:
        validated_url, pinned_ips = validate_url_with_ips(image_url)
    except ValueError as exc:
        logger.error(f"Rejected image URL {image_url}: {exc}")
        return None

    import urllib.parse as _urlparse

    hostname = _urlparse.urlparse(validated_url).hostname or ""

    try:
        with pinned_dns(hostname, pinned_ips):
            try:
                response = http_get(validated_url, timeout=timeout_seconds)
            except TypeError:
                # Fallback for tests that simulate environments without timeout support
                response = http_get(validated_url)
    except Exception as e:
        logger.error(f"Failed to fetch image from {image_url}: {str(e)}")
        return None

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


def fetch_and_resize_remote_image(
    image_url: str,
    dimensions: tuple[int, int],
    timeout_seconds: float = 40.0,
) -> Image.Image | None:
    """Fetch a remote image and return a resized detached copy.

    The hostname is validated and DNS-pinned for the duration of the fetch
    to mitigate DNS-rebinding SSRF (JTN-656).
    """
    try:
        validated_url, pinned_ips = validate_url_with_ips(image_url)
    except ValueError as exc:
        logger.error(f"Rejected remote image URL {image_url}: {exc}")
        return None

    import urllib.parse as _urlparse

    hostname = _urlparse.urlparse(validated_url).hostname or ""

    from contextlib import closing

    from utils.image_loader import AdaptiveImageLoader

    loader = AdaptiveImageLoader()
    # On low-memory devices, stream to disk first so large remote images do not
    # require a full in-memory response buffer before Pillow can decode them.
    if loader.is_low_resource:
        tmp_path = None
        try:
            with pinned_dns(hostname, pinned_ips):
                with closing(
                    http_get(
                        validated_url,
                        timeout=timeout_seconds,
                        stream=True,
                        use_cache=False,
                    )
                ) as response:
                    response.raise_for_status()
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".img"
                    ) as tmp:
                        tmp_path = tmp.name
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                tmp.write(chunk)
            return loader.from_file(tmp_path, dimensions, resize=True)
        except Exception as e:
            logger.error(f"Failed to fetch remote image from {image_url}: {e}")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    logger.warning("Could not delete temp file %s", tmp_path)

    try:
        with pinned_dns(hostname, pinned_ips):
            response = http_get(validated_url, timeout=timeout_seconds)
            response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch remote image from {image_url}: {e}")
        return None

    resized = loader.from_bytesio(BytesIO(response.content), dimensions, resize=True)
    if resized is None:
        logger.error(f"Failed to decode remote image from {image_url}")
    return resized


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
    """Crop and resize an image to the desired dimensions while preserving aspect ratio.

    The image is first cropped to match the target aspect ratio (centred by
    default, or left-aligned when ``"keep-width"`` is present in
    *image_settings*), then scaled to the exact *desired_size*.

    Args:
        image: A ``PIL.Image.Image`` to transform.
        desired_size: A ``(width, height)`` tuple specifying the output
            dimensions in pixels.
        image_settings: An optional list of setting strings.  Passing
            ``"keep-width"`` suppresses the horizontal centring crop so the
            left edge of the original image is preserved.

    Returns:
        A new ``PIL.Image.Image`` resized to exactly *desired_size*.

    Raises:
        ValueError: If the image height or desired height is zero.
    """
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
    """Apply brightness, contrast, saturation, and sharpness adjustments to an image.

    Each parameter defaults to ``1.0`` (no change) when absent from
    *image_settings*.

    Args:
        img: A ``PIL.Image.Image`` to enhance.
        image_settings: A dict with optional float keys ``"brightness"``,
            ``"contrast"``, ``"saturation"``, and ``"sharpness"``.  Values
            below 1.0 reduce the property; values above 1.0 increase it.

    Returns:
        The enhanced ``PIL.Image.Image``.
    """
    from PIL import ImageEnhance

    if image_settings is None:
        image_settings = {}

    # Apply Brightness
    img = ImageEnhance.Brightness(img).enhance(image_settings.get("brightness", 1.0))

    # Apply Contrast
    img = ImageEnhance.Contrast(img).enhance(image_settings.get("contrast", 1.0))

    # Apply Saturation (Color)
    img = ImageEnhance.Color(img).enhance(image_settings.get("saturation", 1.0))

    # Apply Sharpness
    return ImageEnhance.Sharpness(img).enhance(image_settings.get("sharpness", 1.0))


def pad_image_blur(img: Image, dimensions: tuple[int, int]) -> Image:
    """Fit an image into *dimensions* with a blurred letterbox background.

    Creates a background by scaling the image to fill *dimensions* and
    applying a ``BoxBlur``, then pastes a ``contain``-scaled version of the
    original image centred on top.

    Args:
        img: A ``PIL.Image.Image`` to pad.
        dimensions: The target ``(width, height)`` in pixels.

    Returns:
        A new ``PIL.Image.Image`` of exactly *dimensions* with the original
        image centred on a blurred background.
    """
    from PIL import ImageFilter, ImageOps

    bkg = ImageOps.fit(img, dimensions)
    bkg = bkg.filter(ImageFilter.BoxBlur(8))
    img = ImageOps.contain(img, dimensions)

    img_size = img.size
    bkg.paste(
        img, ((dimensions[0] - img_size[0]) // 2, (dimensions[1] - img_size[1]) // 2)
    )
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
    except ImportError:
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
    """Render an HTML string as an image by writing it to a temporary file.

    Prefers Playwright for rendering (better local-asset support); falls back
    to the headless browser subprocess path if Playwright is unavailable.

    Args:
        html_str: The HTML content to render.
        dimensions: A ``(width, height)`` tuple specifying the viewport size
            in pixels.
        timeout_ms: Optional screenshot timeout in milliseconds passed to the
            headless browser subprocess.

    Returns:
        A ``PIL.Image.Image`` of the rendered page, or ``None`` on failure.
    """
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
        logger.error("%s %s", _SCREENSHOT_ERROR_PREFIX, str(e))
    finally:
        if html_file_path and os.path.exists(html_file_path):
            try:
                os.remove(html_file_path)
            except Exception:
                pass

    return image


def _find_browser_command(
    target: str,
    img_file_path: str,
    dimensions: tuple,
    timeout_ms: int | None,
) -> list[str] | None:
    """Return the browser subprocess command for a headless screenshot, or None.

    Iterates through known browser binary paths/names and returns a fully-formed
    argument list for the first one that exists on the system.  Returns ``None``
    when no suitable browser is found.
    """
    browsers = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "chromium",
        "chromium-headless-shell",
        "google-chrome",
    ]

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
            return command

    return None


def take_screenshot(target, dimensions, timeout_ms=None):
    """Capture a screenshot of *target* using a headless browser subprocess.

    Iterates through known browser binaries (Chrome, Chromium) to find one
    available on the system, launches it with ``--headless``, and reads the
    resulting PNG back into a PIL Image.

    Args:
        target: A URL or ``file://`` path to render.
        dimensions: A ``(width, height)`` tuple specifying the viewport size
            in pixels.
        timeout_ms: Optional screenshot timeout in milliseconds passed to the
            browser via ``--timeout``.

    Returns:
        A ``PIL.Image.Image`` of the captured page, or ``None`` if no browser
        is found or the subprocess fails.
    """
    image = None
    img_file_path = None
    try:
        # Create a temporary output file for the screenshot
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
            img_file_path = img_file.name

        command = _find_browser_command(target, img_file_path, dimensions, timeout_ms)

        if command is None:
            logger.error(
                "%s No supported browser found. Install Chromium or Google Chrome.",
                _SCREENSHOT_ERROR_PREFIX,
            )
            return None

        timeout_seconds = min(
            (timeout_ms / 1000) if timeout_ms else _DEFAULT_SCREENSHOT_TIMEOUT_S,
            _MAX_SCREENSHOT_TIMEOUT_S,
        )

        try:
            result = subprocess.run(
                command, capture_output=True, timeout=timeout_seconds
            )
        except FileNotFoundError:
            logger.error("%s Browser binary not found.", _SCREENSHOT_ERROR_PREFIX)
            return None
        except subprocess.TimeoutExpired:
            logger.error("%s Browser process timed out.", _SCREENSHOT_ERROR_PREFIX)
            return None

        # Check if the process failed or the output file is missing
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            logger.error(
                "%s (exit code %s): %s",
                _SCREENSHOT_ERROR_PREFIX,
                result.returncode,
                stderr,
            )
            return None
        if not (img_file_path and os.path.exists(img_file_path)):
            logger.error("%s screenshot file not found", _SCREENSHOT_ERROR_PREFIX)
            return None

        # Load the image using standardized helper
        image = load_image_from_path(img_file_path)
        if image is None:
            logger.error("Failed to load screenshot image from temp file")
            return None

    except Exception as e:
        logger.error("%s %s", _SCREENSHOT_ERROR_PREFIX, str(e))
    finally:
        if img_file_path and os.path.exists(img_file_path):
            try:
                os.remove(img_file_path)
            except Exception:
                pass

    return image

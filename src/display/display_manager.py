import contextlib
import fnmatch
import io
import json
import logging
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from time import perf_counter
from typing import Protocol

from PIL import Image

from display.abstract_display import AbstractDisplay, DeviceConfigLike
from display.mock_display import MockDisplay
from display.rendering_settings import CRISP_IMAGE_SETTING, SCREEN_RENDERING_KEY
from utils.history_cleanup import RetentionPolicy, cleanup_history
from utils.image_utils import (
    FAST_PNG_COMPRESS_LEVEL,
    HISTORY_PNG_COMPRESS_LEVEL,
    apply_image_enhancement,
    change_orientation,
    resize_image,
    save_image_atomic,
    write_bytes_atomic,
)
from utils.time_utils import now_device_tz

logger = logging.getLogger(__name__)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# A processed frame with at most this many colours is stored as a palette PNG.
PALETTE_PNG_MAX_COLOURS = 256


def encode_frame_png(image: Image.Image) -> bytes:
    """Encode a processed frame once, for the preview and the history copy.

    An RGB frame of at most ``PALETTE_PNG_MAX_COLOURS`` colours (a crisp
    frame has six) is stored as an exact palette image. That is lossless,
    several times smaller, and on a Pi Zero 2 W about 50 ms where the
    separate RGB preview and history encodes took about 165 ms.
    """
    frame = image
    if image.mode == "RGB":
        colours = image.getcolors(PALETTE_PNG_MAX_COLOURS)
        if colours is not None:
            from display.crisp import exact_palette_image

            # RGB colours are always tuples; the filter narrows the type.
            palette = [c for _n, c in colours if isinstance(c, tuple)]
            frame = exact_palette_image(image, palette)
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG", compress_level=HISTORY_PNG_COMPRESS_LEVEL)
    return buffer.getvalue()


def panel_copy(image: Image.Image) -> Image.Image:
    """Detached copy of a saved frame, in the mode the panel drivers expect.

    Saved frames may be palette PNGs (see :func:`encode_frame_png`). Drivers
    still get RGB, as they always have: the Inky driver would read a palette
    image's indexes as its own colour codes.
    """
    return image.convert("RGB") if image.mode == "P" else image.copy()


class _DisplayLike(Protocol):
    def display_image(
        self, image: Image.Image, image_settings: list[object] | None = None
    ) -> None: ...


# Try to import hardware displays, but don't fail if they're not available
InkyDisplay: type[AbstractDisplay] | None = None
try:
    from display.inky_display import InkyDisplay as _InkyDisplay

    InkyDisplay = _InkyDisplay
except ImportError:
    logger.info("Inky display not available, hardware support disabled")

WaveshareDisplay: type[AbstractDisplay] | None = None
try:
    from display.waveshare_display import WaveshareDisplay as _WaveshareDisplay

    WaveshareDisplay = _WaveshareDisplay
except ImportError:
    logger.info("Waveshare display not available, hardware support disabled")


class DisplayManager:
    """Manages the display and rendering of images."""

    def __init__(self, device_config: DeviceConfigLike) -> None:
        """
        Initializes the display manager and selects the correct display type
        based on the configuration.

        Args:
            device_config (object): Configuration object containing display settings.

        Raises:
            ValueError: If an unsupported display type is specified.
        """

        # What the panel shows now, as far as display_image knows: the hash
        # of the image it last wrote and the display settings it used. Any
        # other write (history redisplay, blackout, self-test) clears the
        # hash, so the next render is always written.
        self._last_image_hash: str | None = None
        self._last_settings_key: str | None = None
        self._hash_lock = threading.Lock()
        # Serialises driver writes. Callers are meant to go through the
        # refresh loop (RefreshTask.run_display_command), but a panel write
        # takes ~30 s on SPI and two overlapping ones garble the frame, so
        # this is the backstop. It is only ever taken around the driver call
        # and no other lock is acquired while holding it, so it cannot
        # deadlock with the config lock or the refresh-loop condition.
        self._panel_lock = threading.Lock()
        self.device_config = device_config
        self.display: _DisplayLike

        display_type = str(device_config.get_config("display_type", default="inky"))

        if display_type == "mock":
            self.display = MockDisplay(device_config)
        elif display_type == "inky":
            if InkyDisplay is None:
                raise RuntimeError(
                    "Display type 'inky' requested but the Inky hardware driver is unavailable."
                )
            self.display = InkyDisplay(device_config)
        elif fnmatch.fnmatch(display_type, "epd*in*"):
            if WaveshareDisplay is None:
                raise RuntimeError(
                    f"Display type '{display_type}' requested but the Waveshare driver is unavailable."
                )
            # derived from waveshare epd - we assume here that will be consistent
            # otherwise we will have to enshring the manufacturer in the
            # display_type and then have a display_model parameter.  Will leave
            # that for future use if the need arises.
            #
            # see https://github.com/waveshareteam/e-Paper
            self.display = WaveshareDisplay(device_config)
        else:
            raise ValueError(f"Unsupported display type: {display_type}")

    # Approximate count of history entries to avoid scanning the directory on
    # every save.  Reset to None to force a recount on the next prune cycle.
    _history_count_estimate: int | None = None
    # Force a full recount every N increments to correct estimate drift
    _RECOUNT_INTERVAL = 50
    _history_increment_count = 0
    _history_lock = threading.RLock()

    def _history_max_entries(self) -> int:
        """The history count cap from ``history_cleanup.max_count`` (0 = no cap).

        The refresh loop's periodic cleanup reads the same setting, so there
        is one limit to change, not two that override each other.
        """
        device_config = getattr(self, "device_config", None)
        get_config = getattr(device_config, "get_config", None)
        raw = get_config("history_cleanup") if callable(get_config) else None
        return RetentionPolicy.from_config(raw).max_count

    def _prune_history(self, history_dir: str) -> None:
        """Remove the oldest history entries beyond the configured count cap.

        Uses an in-memory count estimate to skip the directory scan when the
        count is clearly below the limit.  The estimate is refreshed whenever
        an actual scan is performed or every _RECOUNT_INTERVAL increments.
        """
        max_entries = self._history_max_entries()
        if max_entries <= 0:
            return
        with self._history_lock:
            if (
                self._history_count_estimate is not None
                and self._history_count_estimate < max_entries
            ):
                self._history_count_estimate += 1
                self._history_increment_count += 1
                # Force periodic recount to correct drift from external deletions
                if self._history_increment_count < self._RECOUNT_INTERVAL:
                    return
                self._history_increment_count = 0
            # Age and free-space limits are left to the refresh loop's
            # periodic cleanup; a save only needs the count cap.
            result = cleanup_history(
                history_dir, max_age_days=0, max_count=max_entries, min_free_bytes=0
            )
            self._history_count_estimate = result.remaining_count

    def _save_history_entry(
        self,
        processed_image: Image.Image | bytes,
        history_meta: Mapping[str, object] | None = None,
    ) -> None:
        """Persist a processed image snapshot and optional JSON sidecar metadata.

        *processed_image* is the frame, or its PNG from :func:`encode_frame_png`
        when the caller already encoded it for the processed preview.

        When ``history_meta`` is None (or empty) we still write the PNG -
        callers like the URL-validation fallback path want the device to
        show the error image - but we skip the JSON sidecar so the
        non-render does NOT count toward Dashboard "Refreshes / Errors"
        KPIs (ISSUE-006). ``utils.refresh_stats.compute_stats`` derives
        those numbers by counting sidecar files; no sidecar = no count.
        """
        history_dir_raw = getattr(self.device_config, "history_image_dir", None)
        if not isinstance(history_dir_raw, str) or not history_dir_raw:
            return

        history_dir = history_dir_raw
        try:
            frame_png = (
                processed_image
                if isinstance(processed_image, bytes)
                else encode_frame_png(processed_image)
            )
            with self._history_lock:
                os.makedirs(history_dir, exist_ok=True)
                timestamp = now_device_tz(self.device_config)
                base_name = f"display_{timestamp.strftime('%Y%m%d_%H%M%S')}"

                png_path: str | None = None
                for attempt in range(1000):
                    candidate = (
                        base_name if attempt == 0 else f"{base_name}_{attempt:03d}"
                    )
                    candidate_path = os.path.join(history_dir, f"{candidate}.png")
                    if os.path.exists(candidate_path):
                        continue
                    # Publish atomically: the history page lists and decodes
                    # display_*.png, so it must never see a half-written file.
                    tmp_path = os.path.join(history_dir, f".{candidate}.png.tmp")
                    try:
                        with open(tmp_path, "wb") as fh:
                            fh.write(frame_png)
                        os.replace(tmp_path, candidate_path)
                    except BaseException:
                        with contextlib.suppress(OSError):
                            os.remove(tmp_path)
                        raise
                    base_name = candidate
                    png_path = candidate_path
                    break

                if png_path is None:
                    raise OSError("Unable to allocate a unique history snapshot path")
        except (OSError, ValueError, RuntimeError):
            logger.exception("Failed to save history snapshot image")
            return
        # Skip the sidecar entirely when there's no metadata to record
        # (callers explicitly opting out). The PNG above is still on disk.
        if not history_meta:
            self._prune_history(history_dir)
            return
        try:
            meta_payload = dict(history_meta)
            meta_payload.setdefault("refresh_time", timestamp.isoformat())
            with open(
                os.path.join(history_dir, f"{base_name}.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                json.dump(meta_payload, fh)
        except (OSError, TypeError, ValueError):
            logger.exception("Failed to persist history metadata for %s", base_name)
        self._prune_history(history_dir)

    @staticmethod
    def _save_preview(image: Image.Image, path: str) -> None:
        """Atomically rewrite a current/processed preview PNG.

        These files are rewritten on every refresh and read back by
        ``/preview``, ``/api/screenshot`` and ``restore_last_frame`` after a
        reboot, so a torn write must never replace the previous frame. They
        are local working copies, so fast compression beats a smaller file.
        """
        save_image_atomic(
            image, path, format="PNG", compress_level=FAST_PNG_COMPRESS_LEVEL
        )

    def _save_current(self, image: Image.Image, source_png: str | None) -> None:
        """Write the unprocessed preview, copying *source_png* when given.

        *source_png* is a PNG file that already holds exactly *image* (the
        plugin's cache file), so copying its bytes gives the same picture
        without a second PNG encode. If the copy fails the image is encoded
        as before.
        """
        path = self.device_config.current_image_file
        if source_png is not None:
            try:
                with open(source_png, "rb") as fh:
                    data = fh.read()
                if not data.startswith(_PNG_SIGNATURE):
                    raise ValueError("not a PNG file")
                write_bytes_atomic(data, path)
                return
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Could not copy %s to the current image (%s); encoding it",
                    source_png,
                    exc,
                )
        self._save_preview(image, path)

    def _maybe_crisp(
        self, image: Image.Image, image_settings: list[object]
    ) -> Image.Image:
        """Snap rendered-UI frames to the panel's pure colours when enabled.

        Applies when the plugin declared ``"crisp"`` in its image settings,
        the device's screen rendering setting is "auto" (the default) and the
        display offers a crisp conversion (colour Inky drivers). The result
        is what the preview and history save, so redisplaying it later keeps
        the undithered look without any plugin context.
        """
        if CRISP_IMAGE_SETTING not in image_settings:
            return image
        device_image_settings = self.device_config.get_config("image_settings")
        mode = (
            device_image_settings.get(SCREEN_RENDERING_KEY, "auto")
            if isinstance(device_image_settings, Mapping)
            else "auto"
        )
        if mode != "auto":
            return image
        crisp_frame = getattr(self.display, "crisp_frame", None)
        if not callable(crisp_frame):
            return image
        t0 = perf_counter()
        converted = crisp_frame(image)
        if not isinstance(converted, Image.Image):
            return image
        logger.info("Crisp conversion took %d ms", (perf_counter() - t0) * 1000)
        return converted

    def _settings_key(self, image_settings: Sequence[object]) -> str:
        """Fingerprint every setting that changes the frame for the same image.

        Two renders with the same image hash only produce the same panel frame
        if the orientation, resolution, inversion, device image settings
        (saturation, contrast, screen rendering...) and the plugin's own image
        settings are unchanged too.
        """
        settings = {
            "orientation": self.device_config.get_config("orientation"),
            "resolution": list(self.device_config.get_resolution()),
            "inverted": bool(self.device_config.get_config("inverted_image")),
            "device_image_settings": self.device_config.get_config("image_settings"),
            "image_settings": list(image_settings),
        }
        return json.dumps(settings, sort_keys=True, default=str)

    def panel_shows(
        self, image_hash: str | None, image_settings: Sequence[object] | None = None
    ) -> bool:
        """Return whether the panel already shows *image_hash* as it would now.

        True only when the last :meth:`display_image` wrote this image with
        the current display settings and nothing else has been written since. The
        refresh loop asks this before pushing a render, instead of comparing
        with the last successful refresh, which knows nothing about error
        cards, history redisplays or display-settings changes made since.
        """
        if image_hash is None:
            return False
        settings_key = self._settings_key(image_settings or [])
        with self._hash_lock:
            return self._on_panel(image_hash, settings_key)

    def _on_panel(self, image_hash: str, key: str) -> bool:
        """Compare with the last write. The caller holds ``_hash_lock``."""
        return image_hash == self._last_image_hash and key == self._last_settings_key

    def _write_panel(self, image: Image.Image, image_settings: list[object]) -> None:
        """Push *image* to the driver, one write at a time."""
        with self._panel_lock:
            self.display.display_image(image, image_settings)

    def display_image(
        self,
        image: Image.Image,
        image_settings: list[object] | None = None,
        history_meta: Mapping[str, object] | None = None,
        on_image_saved: Callable[[dict[str, int]], object] | None = None,
        image_hash: str | None = None,
        source_png: str | None = None,
    ) -> dict[str, int | str]:
        """
        Delegates image rendering to the appropriate display instance.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): List of settings to modify image rendering.
            history_meta (dict, optional): Metadata persisted alongside the
                history snapshot.
            on_image_saved (callable, optional): Invoked once the processed
                image has been written to disk but before the (slow) hardware
                push.  Used by the manual-update path (JTN-786) to release the
                API caller without waiting for the SPI write to finish.
                Receives a metrics dict ``{"preprocess_ms": int}``.  Exceptions
                raised by the callback are logged but never propagated.
            image_hash (str, optional): ``compute_image_hash(image)`` when the
                caller already has it (the refresh task hashes every render for
                its cache check), so the image is not hashed twice per refresh.
            source_png (str, optional): A PNG file holding exactly *image*
                (the plugin's cache file). It is copied to the current-image
                preview instead of encoding *image* again; pass it only when
                the pixels are unchanged since that file was written.

        Raises:
            ValueError: If no valid display instance is found.
        """
        if image_settings is None:
            image_settings = []

        if not hasattr(self, "display"):
            raise ValueError("No valid display instance initialized.")

        if image_hash is None:
            from utils.image_utils import compute_image_hash

            image_hash = compute_image_hash(image)
        settings_key = self._settings_key(image_settings)
        with self._hash_lock:
            if self._on_panel(image_hash, settings_key):
                logger.info("Image unchanged, skipping display writes")
                return {
                    "preprocess_ms": 0,
                    "display_ms": 0,
                    "display_driver": self.display.__class__.__name__,
                }
            previous = (self._last_image_hash, self._last_settings_key)
            self._last_image_hash = image_hash
            self._last_settings_key = settings_key

        try:
            preprocess_t0 = perf_counter()
            # Save the raw image
            logger.info(f"Saving image to {self.device_config.current_image_file}")
            try:
                self._save_current(image, source_png)
            except (OSError, ValueError, RuntimeError):
                logger.exception("Failed to save current image preview")

            # Resize and adjust orientation
            orientation = self.device_config.get_config("orientation")
            image = change_orientation(
                image, orientation if isinstance(orientation, str) else "horizontal"
            )
            image = resize_image(
                image, self.device_config.get_resolution(), image_settings
            )
            if self.device_config.get_config("inverted_image"):
                image = image.rotate(180)
            device_image_settings = self.device_config.get_config("image_settings")
            image = apply_image_enhancement(
                image,
                (
                    device_image_settings
                    if isinstance(device_image_settings, Mapping)
                    else None
                ),
            )
            image = self._maybe_crisp(image, image_settings)
            # One encode serves the processed preview and the history copy.
            frame_png: bytes | None
            try:
                frame_png = encode_frame_png(image)
            except (OSError, ValueError, RuntimeError):
                logger.exception("Failed to encode the processed frame")
                frame_png = None
            if frame_png is not None:
                try:
                    write_bytes_atomic(
                        frame_png, self.device_config.processed_image_file
                    )
                except (OSError, ValueError, RuntimeError):
                    logger.exception("Failed to save processed image preview")
                self._save_history_entry(frame_png, history_meta=history_meta)
            preprocess_ms = int((perf_counter() - preprocess_t0) * 1000)

            # JTN-786: signal the caller that the image is safely on disk
            # BEFORE the slow SPI write below.  On a Pi Zero 2 W driving an
            # Inky 7.3" Impression the display_image() call below can take
            # ~27s — long enough to blow the manual-update 60s cap when
            # combined with preprocessing.  Firing this callback early lets
            # ``manual_update`` return HTTP 200 while the hardware finishes
            # asynchronously.
            if on_image_saved is not None:
                try:
                    on_image_saved({"preprocess_ms": preprocess_ms})
                except Exception:
                    logger.exception("on_image_saved callback failed")

            # Pass to the concrete instance to render to the device.
            display_t0 = perf_counter()
            self._write_panel(image, image_settings)
            display_ms = int((perf_counter() - display_t0) * 1000)
        except Exception:
            # Restore the previous hash so the same image can be retried on the
            # next refresh cycle rather than being permanently skipped.
            with self._hash_lock:
                self._last_image_hash, self._last_settings_key = previous
            raise

        return {
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
            "display_driver": self.display.__class__.__name__,
        }

    def show_system_image(
        self, image: Image.Image, *, preprocessed: bool = False
    ) -> dict[str, int | str]:
        """Push a system frame (blackout blank, self-test pattern) to the panel.

        Unlike :meth:`display_image` this skips the preview files and the
        history: a white blackout frame or a test pattern is not "what the
        display is showing" in any sense the dashboard or history should
        remember. *image* must already be at the panel resolution; pass
        ``preprocessed=True`` for a frame that already went through the normal
        pipeline (the saved processed image), so it is not inverted twice.

        The dedup hash is cleared afterwards so the next real refresh is never
        skipped as "unchanged" just because it matches the frame from before
        the system image.

        Raises whatever the display driver raises.
        """
        if not preprocessed and self.device_config.get_config("inverted_image"):
            image = image.rotate(180)
        display_t0 = perf_counter()
        try:
            self._write_panel(image, [])
        finally:
            with self._hash_lock:
                self._last_image_hash = None
        return {
            "display_ms": int((perf_counter() - display_t0) * 1000),
            "display_driver": self.display.__class__.__name__,
        }

    def restore_last_frame(self) -> dict[str, int | str] | None:
        """Re-push the last processed frame after a system image covered it.

        Returns ``None`` when there is no saved frame to restore (fresh
        install), leaving the panel as it is until the next refresh.
        """
        from PIL import Image

        path = getattr(self.device_config, "processed_image_file", None)
        if not isinstance(path, str) or not os.path.isfile(path):
            return None
        with Image.open(path) as img:
            frame = panel_copy(img)
        return self.show_system_image(frame, preprocessed=True)

    def display_preprocessed_image(self, image_path: str) -> dict[str, int | str]:
        """Display an already-processed image file without applying transforms again."""
        from PIL import Image

        with open(image_path, "rb") as fh:
            frame_png = fh.read()
        with Image.open(io.BytesIO(frame_png)) as img:
            image = panel_copy(img)
        preprocess_t0 = perf_counter()
        # The saved frame is already the processed PNG: copy it, don't re-encode.
        write_bytes_atomic(frame_png, self.device_config.current_image_file)
        write_bytes_atomic(frame_png, self.device_config.processed_image_file)
        preprocess_ms = int((perf_counter() - preprocess_t0) * 1000)
        display_t0 = perf_counter()
        self._write_panel(image, [])
        display_ms = int((perf_counter() - display_t0) * 1000)
        # Clear the dedup hash so the next regular refresh is not skipped
        # because it still matches the pre-history image hash (JTN-236).
        with self._hash_lock:
            self._last_image_hash = None
        return {
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
            "display_driver": self.display.__class__.__name__,
        }

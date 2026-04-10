# ADR-0006: WebP encoding on request rather than at generation time

**Status:** Accepted

## Context

E-ink display images are generated as `PIL.Image` objects and saved to disk as PNG files (`current_image.png`, `processed_image.png`, per-plugin PNGs in `static/images/plugins/`). These PNGs are served to the browser dashboard on every page load and history view. PNG is lossless but large; a 600×448 display image is typically 200-400 KB as PNG but 30-60 KB as WebP (quality 85). The web UI loads dozens of history thumbnails, so the bandwidth difference is noticeable especially when the Pi is accessed over Wi-Fi. The question was: encode to WebP when the plugin generates the image, or at request time?

## Decision

WebP is encoded on-the-fly at request time in `src/utils/image_serving.py`. The `maybe_serve_webp()` function checks the `Accept` request header; browsers that advertise `image/webp` receive a WebP-encoded response, others receive the original PNG via `flask.send_from_directory`. Encoding is done with Pillow (`PIL.Image.save(..., format="WEBP", quality=85, method=4)`). An `lru_cache(maxsize=32)` keyed on `(path, mtime, size)` means repeated requests within a server session are served from memory without re-encoding (added in commit `7923b91`, JTN-302).

## Consequences

### Positive
- PNGs remain on disk as the canonical source of truth — display drivers, history export, and backup/restore all work with unmodified files regardless of browser capability.
- No storage duplication: there is no parallel `.webp` file to keep in sync or clean up.
- The `lru_cache` makes the per-request overhead negligible for the small number of images in the history view (maxsize=32 covers the dashboard thumbnail grid).
- Graceful degradation: old browsers or non-browser clients continue to receive PNG with no code changes.

### Negative
- First request for a large history image incurs a Pillow encode operation — measurable (~20-50 ms) on Pi Zero 2 W but within acceptable latency for a dashboard page load.
- The in-process `lru_cache` is lost on restart; a cold-start page load re-encodes all visible images.
- The 32-entry cache is sufficient for the current history thumbnail count but would need tuning if the history page grows significantly.

## Alternatives considered

- **Pre-encode to WebP at generation time** — eliminates the per-request latency but doubles disk usage (PNG + WebP per image) and complicates the history cleanup logic.
- **Store WebP only, not PNG** — would break display drivers (Inky/Waveshare libraries expect PIL.Image or PNG), history export, and backup/restore which all depend on PNG.
- **Serve PNG always** — simplest, but adds 5-10x more bytes per image over the wire on every dashboard load; noticeable on the local Wi-Fi link to a Pi.

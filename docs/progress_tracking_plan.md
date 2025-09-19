### Progress tracking and user clarity for remote vs device work

Goals
- Make it explicit when the system is waiting on: (1) request accepted, (2) provider generating, (3) provider image download, (4) local render/screenshot, (5) preprocess, (6) display.
- Provide timestamps and durations in the UI progress list.
- Optionally show near real‑time updates via SSE.

Phase 1 (done)
- Backend:
  - HTTP latency logging + env timeouts.
  - BasePlugin render template/screenshot timings.
  - AI Image + APOD: record progress steps provider_generate/provider_download/provider_decode.
  - Flask per‑request timing logs.
- UI:
  - Existing progress list consumes steps array; these new steps appear automatically.

Phase 2 (small)
- Add descriptive labels in the UI mapping steps to friendly text:
  - provider_generate → "Provider generating…"
  - provider_download → "Downloading image…"
  - provider_decode → "Decoding image…"
  - template → "Rendering HTML template…"
  - screenshot → "Capturing screenshot…"
- Ensure we always emit steps even on error paths.

Phase 3 (optional, SSE)
- Add a simple Server‑Sent Events endpoint that streams progress as it happens (instead of only at the end):
  - `/events/<request_id>` streams lines like `event: step\ndata: {"name":"provider_generate","ms":1234}`.
  - Client subscribes and updates the progress list live.
- Fallback to current behavior when SSE is not available.

Phase 4 (metrics UX)
- In the success toast, show a compact summary by domain: network vs compute vs device io.
- Expose recent averages per plugin in Settings → Performance.

Environment flags
- INKYPI_HTTP_LOG_LATENCY=1, INKYPI_REQUEST_TIMING=1, INKYPI_SCREENSHOT_TIMEOUT_MS=45000.

Testing
- Use `scripts/diag_network.py` and `scripts/show_benchmarks.py` to validate changes and compare timings.



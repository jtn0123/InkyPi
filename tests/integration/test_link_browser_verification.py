"""A usable HTML document need not wait for every embedded third-party asset."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

from scripts.check_links import verify_browser_pages


def test_public_document_is_verified_while_an_embedded_asset_is_pending() -> None:
    release_asset = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/slow.png":
                release_asset.wait(timeout=40)
                self.send_response(200)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                (
                    "<title>Public resource</title><body>"
                    + "Actual document content " * 20
                    + '<img src="/slow.png"></body>'
                ).encode()
            )

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        result = verify_browser_pages([url])[url]
        assert result["verified"] is True
        assert result["status"] == 200
        assert result["title"] == "Public resource"
    finally:
        release_asset.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

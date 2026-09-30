"""Public-only browser proxy and restricted process options for remote rendering.

Chromium sends HTTP(S)/WebSocket traffic through this per-render proxy with no
DIRECT fallback or loopback bypass. Each connection validates every DNS answer
and connects to the selected numeric address, preventing validation/connect
rebinding. This is separate from the trusted file-template browser.
"""

from __future__ import annotations

import ipaddress
import os
import select
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

from utils.security_utils import validate_url_with_ips

_MAX_BODY = 1024 * 1024
_HOP_HEADERS = {
    "connection",
    "proxy-connection",
    "proxy-authorization",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _is_public_address(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    if not address.is_global or address.is_multicast:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # Translation/tunnelling ranges can encode private IPv4 destinations.
        return address in ipaddress.ip_network("2000::/3") and not (
            address.sixtofour or address.teredo
        )
    return True


def connect_public(url: str) -> socket.socket:
    _, ips = validate_url_with_ips(url)
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # is_global also rejects shared-address space and special translation ranges.
    if parsed.username is not None or any(not _is_public_address(ip) for ip in ips):
        raise ValueError("Remote rendering requires public addresses")
    last_error: OSError | None = None
    for ip in ips:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        upstream = socket.socket(family, socket.SOCK_STREAM)
        upstream.settimeout(5)
        try:
            # No hostname is resolved a second time at the connection boundary.
            upstream.connect((ip, port))
            return upstream
        except OSError as error:
            upstream.close()
            last_error = error
    raise last_error or OSError("No public address available")


def _relay(client: socket.socket, upstream: socket.socket) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        readable, _, _ = select.select([client, upstream], [], [], 1)
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            destination = upstream if source is client else client
            destination.sendall(data)


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # URLs and browser headers can contain credentials; do not log them.
        return

    def _request_details(self, tunnel: bool) -> tuple[SplitResult, int]:
        target = f"https://{self.path}/" if tunnel else self.path
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or (
            not tunnel and parsed.scheme != "http"
        ):
            raise ValueError("Invalid proxy request")
        if tunnel and parsed.port != 443:
            raise ValueError("Only HTTPS tunnels are supported")
        if self.headers.get("Transfer-Encoding") or self.headers.get("Upgrade"):
            raise ValueError("Unsupported proxy framing")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= _MAX_BODY:
            raise ValueError("Request body is too large")
        return parsed, length

    def _send_request(
        self, upstream: socket.socket, parsed: SplitResult, length: int
    ) -> None:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        headers = [
            f"{self.command} {path} HTTP/1.1",
            f"Host: {parsed.netloc}",
            "Connection: close",
            f"Content-Length: {length}",
        ]
        headers.extend(
            f"{name}: {value}"
            for name, value in self.headers.items()
            if name.lower() not in _HOP_HEADERS
        )
        upstream.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("latin-1"))
        if length:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete request body")
            upstream.sendall(body)

    def _forward(self, tunnel: bool = False) -> None:
        self.close_connection = True
        upstream: socket.socket | None = None
        started = False
        try:
            parsed, length = self._request_details(tunnel)
            upstream = connect_public(parsed.geturl())
            if tunnel:
                self.send_response(200, "Connection Established")
                self.end_headers()
                self.wfile.flush()
            else:
                self._send_request(upstream, parsed, length)
            started = True
            _relay(self.connection, upstream)
        except ValueError:
            if not started:
                self.send_error(403, "Remote destination or request blocked")
        except OSError:
            if not started:
                self.send_error(502, "Remote destination unavailable")
        finally:
            if upstream:
                upstream.close()

    def do_CONNECT(self) -> None:
        self._forward(tunnel=True)

    def do_GET(self) -> None:
        self._forward()

    do_HEAD = do_GET
    do_POST = do_GET
    do_OPTIONS = do_GET


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self._slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", 0), _ProxyHandler)

    def verify_request(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any
    ) -> bool:
        if not isinstance(request, socket.socket):
            return False
        request.settimeout(5)
        return self._slots.acquire(blocking=False)

    def process_request_thread(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


@contextmanager
def public_proxy() -> Iterator[int]:
    server = _ProxyServer()
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def remote_process_options(directory: str) -> dict[str, Any]:
    """Strip inherited secrets; when the app is root, run Chromium as nobody."""
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT")
        if key in os.environ
    }
    environment.update(
        {
            "HOME": directory,
            "TMPDIR": directory,
            "XDG_CONFIG_HOME": directory,
            "XDG_CACHE_HOME": directory,
        }
    )
    options: dict[str, Any] = {"env": environment, "cwd": directory}
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        import pwd

        account = pwd.getpwnam("nobody")
        if not account.pw_uid:
            raise RuntimeError("Remote Chromium requires an unprivileged account")
        for path in (Path(directory), *Path(directory).iterdir()):
            os.chown(path, account.pw_uid, account.pw_gid)
        options.update(user=account.pw_uid, group=account.pw_gid, extra_groups=[])
    return options

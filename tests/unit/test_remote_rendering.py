"""Remote content must not inherit the trusted file-template browser permissions."""

import http.client
import os
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from utils import image_utils


def test_remote_command_keeps_chromium_security_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/fake/chromium")
    command = image_utils._find_browser_command(
        "https://example.com", "/tmp/out.png", (800, 480), 1000
    )
    assert command
    assert "--no-sandbox" not in command
    assert "--disable-web-security" not in command
    assert "--allow-file-access-from-files" not in command


def test_trusted_template_retains_local_asset_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/fake/chromium")
    command = image_utils._find_browser_command(
        "file:///tmp/template.html", "/tmp/out.png", (800, 480), 1000
    )
    assert command and "--allow-file-access-from-files" in command


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1:1234/private",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://10.0.0.1/",
        "https://192.168.1.1/",
    ],
)
def test_private_canaries_are_rejected_before_connect(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from utils.remote_rendering import public_proxy

    connections = []
    original = socket.socket.connect

    def connect(sock: socket.socket, address: Any) -> None:
        connections.append(address)
        return original(sock, address)

    with public_proxy() as port:
        monkeypatch.setattr(socket.socket, "connect", connect)
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        client.request("GET", target)
        response = client.getresponse()
        assert response.status == 403
        response.read()
        client.close()
    assert connections == [("127.0.0.1", port)]


def test_dns_rebinding_is_pinned_to_validated_numeric_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils import remote_rendering as remote

    monkeypatch.setattr(
        remote, "validate_url_with_ips", lambda url: (url, ("93.184.215.14",))
    )
    connected = []

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            pass

        def connect(self, address: Any) -> None:
            connected.append(address)

    monkeypatch.setattr(socket, "socket", lambda *_: FakeSocket())
    remote.connect_public("https://rebinding.test/page")
    assert connected == [("93.184.215.14", 443)]


def test_mixed_public_private_dns_answers_are_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils import remote_rendering as remote

    monkeypatch.setattr(
        remote,
        "validate_url_with_ips",
        lambda url: (url, ("93.184.215.14", "10.0.0.1")),
    )
    with pytest.raises(ValueError):
        remote.connect_public("https://mixed.test/")


@pytest.mark.parametrize(
    "ip", ["100.64.0.1", "64:ff9b::7f00:1", "2002:7f00:1::", "224.0.0.1"]
)
def test_special_address_ranges_are_blocked(ip: str) -> None:
    from utils.remote_rendering import _is_public_address

    assert not _is_public_address(ip)


@pytest.mark.parametrize(
    "target,headers",
    [
        ("http://127.0.0.1/", {}),
        ("file:///etc/passwd", {}),
        ("http://public.test/", {"Transfer-Encoding": "chunked"}),
        ("http://public.test/", {"Content-Length": "1048577"}),
    ],
)
def test_proxy_rejects_unsafe_destinations_and_framing(
    target: str, headers: dict[str, str]
) -> None:
    from utils.remote_rendering import public_proxy

    with public_proxy() as port:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        client.request("GET", target, headers=headers)
        assert client.getresponse().status == 403
        client.close()


def test_public_page_and_redirect_private_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils import remote_rendering as remote

    requests: list[str] = []

    class Canary(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1/private-canary")
            self.end_headers()

    canary = ThreadingHTTPServer(("127.0.0.1", 0), Canary)
    thread = threading.Thread(target=canary.serve_forever, daemon=True)
    thread.start()
    original = remote.connect_public

    def controlled_connect(url: str) -> socket.socket:
        if url == "http://public.test/start":
            return socket.create_connection(
                ("127.0.0.1", canary.server_port), timeout=2
            )
        return original(url)

    monkeypatch.setattr(remote, "connect_public", controlled_connect)
    try:
        with remote.public_proxy() as port:
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            client.request("GET", "http://public.test/start")
            response = client.getresponse()
            assert response.status == 302
            redirected = response.getheader("Location")
            assert redirected is not None
            response.read()
            client.close()
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            client.request("GET", redirected)
            assert client.getresponse().status == 403
            client.close()
        assert requests == ["/start"]
    finally:
        canary.shutdown()
        canary.server_close()
        thread.join(timeout=1)


def test_remote_process_drops_secrets_and_root_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pwd
    from types import SimpleNamespace

    from utils import remote_rendering as remote

    monkeypatch.setenv("SECRET_KEY", "fixture-secret")
    monkeypatch.setenv("INKYPI_AUTH_PIN", "fixture-pin")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=65534, pw_gid=65534)
    )
    ownership = []
    monkeypatch.setattr(os, "chown", lambda *args: ownership.append(args))
    options = remote.remote_process_options(str(tmp_path))
    assert "SECRET_KEY" not in options["env"]
    assert "INKYPI_AUTH_PIN" not in options["env"]
    assert options["user"] == 65534
    assert options["group"] == 65534
    assert options["extra_groups"] == []
    assert ownership


@pytest.mark.parametrize(
    "method,target,headers,status",
    [
        ("CONNECT", "public.test:80", {}, 403),
        ("GET", "https://public.test/", {}, 403),
        ("GET", "http://public.test/", {"Content-Length": "junk"}, 403),
        ("GET", "http://public.test/", {"Upgrade": "websocket"}, 403),
        ("GET", "http://public.test/", {}, 502),
    ],
)
def test_proxy_failure_responses(
    method: str,
    target: str,
    headers: dict[str, str],
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils import remote_rendering as remote

    def unavailable(url: str) -> socket.socket:
        raise OSError("fixture network failure")

    monkeypatch.setattr(remote, "connect_public", unavailable)
    with remote.public_proxy() as port:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        client.request(method, target, headers=headers)
        response = client.getresponse()
        assert response.status == status
        response.read()
        client.close()


def test_public_connect_tunnel_relays_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils import remote_rendering as remote

    upstream, canary = socket.socketpair()
    monkeypatch.setattr(remote, "connect_public", lambda _: upstream)
    try:
        with remote.public_proxy() as port:
            browser = socket.create_connection(("127.0.0.1", port), timeout=2)
            browser.sendall(
                b"CONNECT public.test:443 HTTP/1.1\r\nHost: public.test:443\r\n\r\n"
            )
            headers = b""
            while not headers.endswith(b"\r\n\r\n"):
                headers += browser.recv(1)
            assert headers.startswith(b"HTTP/1.1 200")
            browser.sendall(b"browser fixture")
            canary.settimeout(2)
            assert canary.recv(100) == b"browser fixture"
            canary.sendall(b"upstream fixture")
            assert browser.recv(100) == b"upstream fixture"
            browser.close()
    finally:
        canary.close()
        upstream.close()


def test_public_connections_retry_only_validated_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils import remote_rendering as remote

    monkeypatch.setattr(
        remote,
        "validate_url_with_ips",
        lambda url: (url, ("93.184.215.14", "93.184.215.15")),
    )
    attempts = []
    closed = []

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            pass

        def connect(self, address: Any) -> None:
            attempts.append(address)
            raise OSError("fixture unavailable")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(socket, "socket", lambda *_: FakeSocket())
    with pytest.raises(OSError):
        remote.connect_public("http://public.test/")
    assert attempts == [("93.184.215.14", 80), ("93.184.215.15", 80)]
    assert len(closed) == 2

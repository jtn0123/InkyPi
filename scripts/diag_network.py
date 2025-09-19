#!/usr/bin/env python3
"""
Quick network diagnostics for InkyPi devices.

Measures DNS resolve time, TCP connect time, TLS handshake, TTFB, and total
download time for a set of URLs. Prints a compact table for fast triage.

Usage:
  python3 scripts/diag_network.py --urls https://api.openweathermap.org https://images.nasa.gov
  python3 scripts/diag_network.py  # uses built-in defaults
"""

from __future__ import annotations

import argparse
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from typing import Iterable


@dataclass
class Timings:
    dns_ms: int
    connect_ms: int
    tls_ms: int
    ttfb_ms: int
    total_ms: int
    ok: bool
    status: int | None


def measure_http(url: str, timeout: float = 15.0) -> Timings:
    from urllib.parse import urlparse

    p = urlparse(url)
    host = p.hostname or url
    port = p.port or (443 if p.scheme == "https" else 80)
    path = p.path or "/"
    if p.query:
        path += f"?{p.query}"

    t0 = time.perf_counter()
    # DNS
    try:
        addr_info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        dns_ms = int((time.perf_counter() - t0) * 1000)
    except Exception:
        return Timings(dns_ms=ms(time.perf_counter() - t0), connect_ms=-1, tls_ms=-1, ttfb_ms=-1, total_ms=-1, ok=False, status=None)

    # Connect
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t1 = time.perf_counter()
    try:
        s.connect(addr_info[0][4])
        connect_ms = int((time.perf_counter() - t1) * 1000)
    except Exception:
        s.close()
        return Timings(dns_ms=dns_ms, connect_ms=ms(time.perf_counter() - t1), tls_ms=-1, ttfb_ms=-1, total_ms=-1, ok=False, status=None)

    # TLS
    tls_ms = 0
    if p.scheme == "https":
        ctx = ssl.create_default_context()
        t2 = time.perf_counter()
        try:
            s = ctx.wrap_socket(s, server_hostname=host)
            tls_ms = int((time.perf_counter() - t2) * 1000)
        except Exception:
            s.close()
            return Timings(dns_ms=dns_ms, connect_ms=connect_ms, tls_ms=ms(time.perf_counter() - t2), ttfb_ms=-1, total_ms=-1, ok=False, status=None)

    # HTTP request + TTFB
    req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: InkyPiDiag/1.0\r\nConnection: close\r\n\r\n".encode()
    t3 = time.perf_counter()
    status_code: int | None = None
    try:
        s.sendall(req)
        buf = b""
        # Read until first CRLF of status line
        while b"\r\n" not in buf:
            chunk = s.recv(1)
            if not chunk:
                break
            buf += chunk
        # Parse status line
        try:
            line = buf.decode(errors="ignore").strip()
            if line.startswith("HTTP/1."):
                parts = line.split()
                status_code = int(parts[1])
        except Exception:
            status_code = None
        ttfb_ms = int((time.perf_counter() - t3) * 1000)
        # Drain rest
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
    except Exception:
        s.close()
        return Timings(dns_ms=dns_ms, connect_ms=connect_ms, tls_ms=tls_ms, ttfb_ms=ms(time.perf_counter() - t3), total_ms=-1, ok=False, status=status_code)
    finally:
        try:
            s.close()
        except Exception:
            pass

    total_ms = int((time.perf_counter() - t0) * 1000)
    ok = status_code is not None and 200 <= status_code < 500
    return Timings(dns_ms=dns_ms, connect_ms=connect_ms, tls_ms=tls_ms, ttfb_ms=ttfb_ms, total_ms=total_ms, ok=ok, status=status_code)


def ms(x: float) -> int:
    return int(x * 1000)


def main(urls: Iterable[str]) -> int:
    print("url                                       dns  conn  tls  ttfb  total  status  ok")
    print("--------------------------------------------------------------------------------")
    for u in urls:
        t = measure_http(u)
        print(
            f"{u[:40]:<40}  {t.dns_ms:>4}  {t.connect_ms:>4}  {t.tls_ms:>4}  {t.ttfb_ms:>5}  {t.total_ms:>5}  {str(t.status or '-'):<6}  {'Y' if t.ok else 'N'}"
        )
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--urls",
        nargs="*",
        default=[
            "https://api.openweathermap.org",
            "https://api.open-meteo.com",
            "https://images-api.nasa.gov/search?q=apod",
            "https://www.google.com/generate_204",
        ],
        help="URLs to test",
    )
    args = p.parse_args()
    sys.exit(main(args.urls))



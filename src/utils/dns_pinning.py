"""Per-thread DNS pinning for SSRF-validated fetches (JTN-656)."""

from __future__ import annotations

import ipaddress
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# ---- DNS pinning (SSRF mitigation, JTN-656) --------------------------------
#
# ``validate_url`` resolves DNS up-front to reject private targets, but the
# subsequent HTTP call resolves DNS *again* inside ``urllib3``.  A hostile
# authoritative server can flip the second answer to a private IP (DNS
# rebinding) — bypassing the guard entirely.
#
# The countermeasure here is to pin the resolver to the exact IPs observed at
# validation time for the duration of the fetch.  We do this by monkey-patching
# ``socket.getaddrinfo`` with a thin wrapper keyed on hostname.  The URL
# itself is unchanged, so TLS SNI and certificate verification still happen
# against the original hostname (we are *not* rewriting the URL host to an
# IP, which would break HTTPS vhost routing and cert matching).
#
# The swap is bounded by a context manager: on entry we stash the currently
# installed ``socket.getaddrinfo`` and replace it with our wrapper; on exit
# we restore exactly what we stashed.  This nests cleanly and plays well
# with test monkeypatches of ``socket.getaddrinfo`` that are set either
# before or after the pin is established.
#
# Concurrency note: ``socket.getaddrinfo`` is a module-level attribute, so
# replacing it affects every thread.  We serialise entry/exit through a
# lock and use a re-entrant pin store so only threads that have actually
# called ``pinned_dns`` see rewritten results.  Other threads' lookups pass
# through unchanged.
#
# Pins are keyed by the ASCII (IDNA) form of the host name, because that is
# the form ``requests``/``urllib3`` hand to ``getaddrinfo``: a pin stored
# under ``exämple.com`` would never match the ``xn--exmple-cua.com`` lookup.
# While a thread holds any pin, a lookup from that thread for any other host
# is refused rather than passed to the real resolver, so a key mismatch
# fails closed instead of silently skipping the pin.

_dns_pin_global_lock = threading.Lock()
_dns_pin_depth: int = 0
_dns_pin_saved: Any = None
_dns_pin_local = threading.local()


def _pin_store() -> dict[str, tuple[str, ...]]:
    store: dict[str, tuple[str, ...]] | None = getattr(_dns_pin_local, "pins", None)
    if store is None:
        store = {}
        _dns_pin_local.pins = store
    return store


def idna_hostname(hostname: str) -> str:
    """Return *hostname* in the lowercase ASCII form an HTTP client resolves.

    ``requests`` converts a non-ASCII host with the ``idna`` package (UTS 46
    mapping, IDNA 2008) before ``urllib3`` calls ``getaddrinfo``, so this does
    the same; Python's built-in ``idna`` codec follows IDNA 2003 and maps some
    names (``straße``) to a different domain.  A trailing root dot is dropped.
    Raises :class:`UnicodeError` (``idna.IDNAError``) for a name that has no
    valid ASCII form, which ``requests`` would refuse as well.
    """
    host = hostname.rstrip(".")
    if host.isascii():
        return host.lower()
    import idna

    return idna.encode(host, uts46=True).decode("ascii").lower()


def _normalize_host(host: Any) -> str | None:
    """Return *host* as its pin key, or None if it is not a usable host name."""
    if isinstance(host, (bytes, bytearray)):
        try:
            host = bytes(host).decode("ascii")
        except UnicodeDecodeError:
            return None
    if not isinstance(host, str) or not host:
        return None
    try:
        return idna_hostname(host)
    except UnicodeError:
        return None


def _coerce_port(port: Any) -> int:
    """Best-effort conversion of *port* to an int; returns 0 on failure."""
    if port is None or port == "":
        return 0
    try:
        return int(port)
    except (TypeError, ValueError):
        return 0


def _addrinfo_for_pinned_ip(ip: str, port_int: int) -> tuple[Any, ...] | None:
    """Build an addrinfo tuple for *ip*, or None if *ip* is not parseable."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        family = socket.AF_INET6
        sockaddr: tuple[Any, ...] = (ip, port_int, 0, 0)
    else:
        family = socket.AF_INET
        sockaddr = (ip, port_int)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def _make_patched_getaddrinfo(original: Any) -> Any:
    """Return a getaddrinfo wrapper that consults the thread-local pin store.

    *original* is the resolver used when the calling thread has no active
    pins.  A thread that holds a pin gets the pinned addresses for that host
    and a resolution error for every other lookup, so a host name that
    doesn't match its pin can never reach the real resolver.
    """

    def _patched_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        pins = _pin_store()
        if not pins:
            return original(host, port, *args, **kwargs)
        key = _normalize_host(host)
        ips = pins.get(key) if key is not None else None
        port_int = _coerce_port(port)
        results: list[Any] = [
            info
            for info in (_addrinfo_for_pinned_ip(ip, port_int) for ip in ips or ())
            if info is not None
        ]
        if not results:
            raise socket.gaierror(
                socket.EAI_NONAME,
                f"DNS lookup of {host!r} refused: only pinned hosts resolve here",
            )
        return results

    return _patched_getaddrinfo


@contextmanager
def pinned_dns(hostname: str, ips: tuple[str, ...] | list[str]) -> Iterator[None]:
    """Context manager that pins ``socket.getaddrinfo(hostname, ...)`` to *ips*.

    Only threads that entered ``pinned_dns`` see rewritten results; other
    threads fall through to the underlying resolver.  Inside the block the
    calling thread can resolve only pinned hosts (see
    :func:`_make_patched_getaddrinfo`).  Intended to bracket an HTTP request
    whose hostname was already validated via
    :func:`utils.security_utils.validate_url_with_ips`.
    """
    global _dns_pin_depth, _dns_pin_saved

    if not hostname:
        yield
        return

    # A name with no ASCII form can't be requested either; keying it on the
    # raw text still installs the pin, so every lookup in the block fails.
    key = _normalize_host(hostname) or hostname.lower()
    store = _pin_store()
    previous_pin = store.get(key)
    store[key] = tuple(ips)

    # Install the wrapper on first entry across all threads; subsequent
    # nested (or concurrent) ``pinned_dns`` calls just bump the depth.
    with _dns_pin_global_lock:
        if _dns_pin_depth == 0:
            _dns_pin_saved = socket.getaddrinfo
            socket.getaddrinfo = _make_patched_getaddrinfo(_dns_pin_saved)
        _dns_pin_depth += 1

    try:
        yield
    finally:
        # Whichever thread brings the depth back to zero restores the
        # original resolver.  Tying the restore to the *installing* thread
        # leaked the wrapper when threads exited out of order (A enters,
        # B enters, A exits, B exits), and the next first entry then stacked
        # a fresh wrapper on top of the leaked one.
        with _dns_pin_global_lock:
            _dns_pin_depth -= 1
            if _dns_pin_depth == 0:
                socket.getaddrinfo = _dns_pin_saved
                _dns_pin_saved = None
        if previous_pin is None:
            store.pop(key, None)
        else:
            store[key] = previous_pin

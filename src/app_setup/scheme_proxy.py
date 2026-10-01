"""Trust a single TLS proxy's scheme only when its direct peer is configured."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIApplication, WSGIEnvironment


class TrustedSchemeProxy:
    def __init__(self, app: WSGIApplication, peers: str) -> None:
        self.app = app
        try:
            self.networks = tuple(
                ipaddress.ip_network(value.strip(), strict=False)
                for value in peers.split(",")
                if value.strip()
            )
            if any(network.prefixlen == 0 for network in self.networks):
                raise ValueError("unrestricted network")
        except ValueError as error:
            raise ValueError(
                "INKYPI_TRUSTED_PROXIES must contain specific IP addresses or CIDRs"
            ) from error

    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> Iterable[bytes]:
        try:
            peer = ipaddress.ip_address(environ.get("REMOTE_ADDR", ""))
            trusted = any(peer in network for network in self.networks)
        except ValueError:
            trusted = False
        # A single trusted proxy must overwrite the incoming header. Never
        # reinterpret forwarded host, port, path or client address here.
        protocol = environ.pop("HTTP_X_FORWARDED_PROTO", "")
        if trusted and protocol in {"http", "https"}:
            environ["wsgi.url_scheme"] = protocol
        return self.app(environ, start_response)

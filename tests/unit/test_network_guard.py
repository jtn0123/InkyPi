"""The suite-wide network guard in tests/conftest.py (no_outside_network)."""

from __future__ import annotations

import _socket
import socket
from collections.abc import Iterator

import pytest
from tests.conftest import NETWORK_ATTEMPTS, NetworkBlocked

# TEST-NET-1 (RFC 5737): never routed, so nothing is reached even if the
# guard failed and the connect went out.
_OUTSIDE = ("192.0.2.1", 80)


@pytest.fixture()
def attempts(request: pytest.FixtureRequest) -> Iterator[list[str]]:
    """The guard's record for this test, emptied afterwards on purpose."""
    recorded = request.node.stash[NETWORK_ATTEMPTS]
    yield recorded
    recorded.clear()


def test_connect_outside_is_refused_and_recorded(attempts: list[str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlocked):
            sock.connect(_OUTSIDE)
        with pytest.raises(NetworkBlocked):
            sock.connect_ex(_OUTSIDE)
    assert attempts == ["connect to 192.0.2.1:80"] * 2


def test_refusal_looks_like_being_offline(attempts: list[str]) -> None:
    # Code under test catches OSError for "no network"; it must take that path.
    with pytest.raises(OSError):
        socket.create_connection(_OUTSIDE, timeout=1)
    assert attempts == ["connect to 192.0.2.1:80"]


def test_dns_lookup_of_a_public_name_is_refused(attempts: list[str]) -> None:
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("example.com", 443)
    assert attempts == ["DNS lookup of example.com"]


def test_this_machine_is_still_reachable(attempts: list[str]) -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with socket.create_connection(server.getsockname(), timeout=2):
            pass
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo("192.0.2.1", 80)  # a literal needs no lookup
    assert attempts == []


@pytest.mark.allow_network
def test_allow_network_leaves_sockets_alone() -> None:
    assert socket.socket.connect is _socket.socket.connect
    assert socket.socket.connect_ex is _socket.socket.connect_ex

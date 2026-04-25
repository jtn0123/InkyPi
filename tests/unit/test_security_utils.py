# pyright: reportMissingImports=false
"""Tests for utils.security_utils — URL and file-path validation."""

import socket

import pytest

from utils.security_utils import (
    URLValidationError,
    validate_file_path,
    validate_url,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_getaddrinfo_public(host, port, *args, **kwargs):
    """Return a fake getaddrinfo result pointing to a public IP."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _mock_getaddrinfo_private(host, port, *args, **kwargs):
    """Return a fake getaddrinfo result pointing to a private IP."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0))]


def _mock_getaddrinfo_loopback(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]


def _mock_getaddrinfo_link_local(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]


def _mock_getaddrinfo_fail(host, port, *args, **kwargs):
    raise socket.gaierror("Name resolution failed")


# ---------------------------------------------------------------------------
# URL validation — happy paths
# ---------------------------------------------------------------------------


class TestValidateUrlAccepted:
    def test_http_url_passes(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_public)
        assert validate_url("http://example.com") == "http://example.com"

    def test_https_url_passes(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_public)
        assert validate_url("https://example.com/page") == "https://example.com/page"

    def test_url_with_port_passes(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_public)
        assert (
            validate_url("http://example.com:8080/path")
            == "http://example.com:8080/path"
        )

    def test_url_with_query_passes(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_public)
        url = "https://example.com/search?q=test&page=1"
        assert validate_url(url) == url


# ---------------------------------------------------------------------------
# URL validation — scheme rejection
# ---------------------------------------------------------------------------


class TestValidateUrlSchemeRejected:
    def test_file_scheme_rejected(self):
        with pytest.raises(ValueError, match="scheme must be http or https"):
            validate_url("file:///etc/passwd")

    def test_javascript_scheme_rejected(self):
        with pytest.raises(ValueError, match="scheme must be http or https"):
            validate_url("javascript:alert(1)")

    def test_data_scheme_rejected(self):
        with pytest.raises(ValueError, match="scheme must be http or https"):
            validate_url("data:text/html,<h1>hi</h1>")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError, match="scheme must be http or https"):
            validate_url("ftp://files.example.com/readme.txt")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_url("")


# ---------------------------------------------------------------------------
# URL validation — hostname checks
# ---------------------------------------------------------------------------


class TestValidateUrlHostname:
    def test_no_hostname_rejected(self):
        with pytest.raises(ValueError, match="must include a hostname"):
            validate_url("http://")

    def test_localhost_rejected(self):
        with pytest.raises(ValueError, match="must not target localhost"):
            validate_url("http://localhost:8080")

    def test_localhost_case_insensitive(self):
        with pytest.raises(ValueError, match="must not target localhost"):
            validate_url("http://LOCALHOST/path")


# ---------------------------------------------------------------------------
# URL validation — IP address checks
# ---------------------------------------------------------------------------


class TestValidateUrlIpRejected:
    def test_loopback_ipv4_rejected(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_loopback)
        with pytest.raises(
            ValueError, match="private.*loopback.*link-local.*reserved.*multicast"
        ):
            validate_url("http://127.0.0.1")

    def test_ipv6_loopback_rejected(self, monkeypatch):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **kw: [
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))
            ],
        )
        with pytest.raises(ValueError):
            validate_url("http://[::1]")

    def test_private_10x_rejected(self, monkeypatch):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **kw: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))
            ],
        )
        with pytest.raises(ValueError):
            validate_url("http://10.0.0.1")

    def test_private_172_16_rejected(self, monkeypatch):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **kw: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.16.0.1", 0))
            ],
        )
        with pytest.raises(ValueError):
            validate_url("http://172.16.0.1")

    def test_private_192_168_rejected(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_private)
        with pytest.raises(ValueError):
            validate_url("http://192.168.1.1")

    def test_link_local_rejected(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_link_local)
        with pytest.raises(ValueError):
            validate_url("http://169.254.169.254/latest/meta-data/")


# ---------------------------------------------------------------------------
# URL validation — DNS resolution
# ---------------------------------------------------------------------------


class TestValidateUrlDns:
    def test_dns_resolving_to_private_rejected(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_private)
        with pytest.raises(ValueError):
            validate_url("http://evil.example.com")

    def test_unresolvable_host_rejected(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo_fail)
        with pytest.raises(ValueError, match="Cannot resolve hostname"):
            validate_url("http://nonexistent.invalid")

    def test_overlong_hostname_rejected_before_dns(self, monkeypatch):
        def fail_getaddrinfo(*args, **kwargs):
            pytest.fail("overlong hostnames should be rejected before DNS lookup")

        monkeypatch.setattr(socket, "getaddrinfo", fail_getaddrinfo)
        with pytest.raises(ValueError, match="Cannot resolve hostname"):
            validate_url(f"https://{'a' * 64}.example.com/image.jpg")

    def test_idna_resolution_error_is_normalized(self, monkeypatch):
        def raise_unicode_error(*args, **kwargs):
            raise UnicodeError("label too long")

        monkeypatch.setattr(socket, "getaddrinfo", raise_unicode_error)
        with pytest.raises(ValueError, match="Cannot resolve hostname"):
            validate_url("https://example.com/image.jpg")


# ---------------------------------------------------------------------------
# File path validation — happy paths
# ---------------------------------------------------------------------------


class TestValidateFilePathAccepted:
    def test_valid_path_within_directory(self, tmp_path):
        allowed = tmp_path / "uploads"
        allowed.mkdir()
        target = allowed / "image.png"
        target.touch()
        result = validate_file_path(str(target), str(allowed))
        assert result == str(target.resolve())

    def test_nested_subdirectory(self, tmp_path):
        allowed = tmp_path / "uploads"
        sub = allowed / "sub" / "deep"
        sub.mkdir(parents=True)
        target = sub / "file.txt"
        target.touch()
        result = validate_file_path(str(target), str(allowed))
        assert result == str(target.resolve())


# ---------------------------------------------------------------------------
# File path validation — rejection
# ---------------------------------------------------------------------------


class TestValidateFilePathRejected:
    def test_traversal_rejected(self, tmp_path):
        allowed = tmp_path / "uploads"
        allowed.mkdir()
        malicious = str(allowed / ".." / ".." / "etc" / "passwd")
        with pytest.raises(ValueError, match="outside the allowed directory"):
            validate_file_path(malicious, str(allowed))

    def test_absolute_path_outside_rejected(self, tmp_path):
        allowed = tmp_path / "uploads"
        allowed.mkdir()
        with pytest.raises(ValueError, match="outside the allowed directory"):
            validate_file_path("/etc/passwd", str(allowed))

    def test_symlink_escaping_rejected(self, tmp_path):
        allowed = tmp_path / "uploads"
        allowed.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        link = allowed / "escape.txt"
        link.symlink_to(outside)
        with pytest.raises(ValueError, match="outside the allowed directory"):
            validate_file_path(str(link), str(allowed))


# ---------------------------------------------------------------------------
# URLValidationError (JTN-776)
# ---------------------------------------------------------------------------


class TestURLValidationError:
    """The typed error must stay catchable as RuntimeError *and* return a
    whitelisted response message that breaks CodeQL taint flow."""

    def test_is_runtime_error(self):
        err = URLValidationError("Invalid URL: scheme must be http or https")
        assert isinstance(err, RuntimeError)
        assert "Invalid URL" in str(err)

    def test_safe_message_passes_through_whitelisted_reason(self):
        err = URLValidationError("Invalid URL: URL scheme must be http or https")
        # The reason "URL scheme must be http or https" is one of the hardcoded
        # validator strings, so safe_message must return it verbatim.
        assert err.safe_message() == "Invalid URL: URL scheme must be http or https"

    def test_safe_message_falls_back_for_unknown_reason(self):
        err = URLValidationError("Invalid URL: something the user typed")
        # Unknown reason -> generic fallback (this is what satisfies CodeQL).
        assert err.safe_message() == "Invalid URL: URL failed validation"

    def test_safe_message_whitelist_covers_all_validator_errors(self):
        """Every ValueError that validate_url raises must map to a whitelisted
        safe_message. If a new validator error is added without updating the
        whitelist, this test will fail."""
        # Each bad URL below triggers a distinct ValueError branch.
        bad_urls = [
            "",  # empty
            "ftp://example.com/",  # bad scheme
            "http://",  # no hostname
            "http://localhost/",  # localhost literal
            "http://127.0.0.1/",  # private IP literal
        ]
        for url in bad_urls:
            try:
                validate_url(url)
            except ValueError as exc:
                reason = str(exc)
                err = URLValidationError(f"Invalid URL: {reason}")
                # Whitelisted reason -> safe_message returns the real text
                assert (
                    err.safe_message() == f"Invalid URL: {reason}"
                ), f"Reason '{reason}' not on whitelist"
            else:
                pytest.fail(f"Expected ValueError for URL: {url!r}")

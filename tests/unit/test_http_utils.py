import types

import requests


def test_http_get_user_agent_and_default_timeout(monkeypatch):
    import utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    captured = {}

    def fake_get(self, url, **kwargs):  # type: ignore[no-redef]
        captured["headers"] = kwargs.get("headers")
        captured["timeout"] = kwargs.get("timeout")

        class R:
            status_code = 200

            def json(self):
                return {}

            content = b""

        return R()

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)

    http_utils.http_get("https://example.com")

    assert isinstance(captured.get("headers"), dict)
    assert captured["headers"].get("User-Agent", "").startswith("InkyPi/")
    assert captured.get("timeout") == http_utils.DEFAULT_TIMEOUT_SECONDS


def test_http_get_timeout_override(monkeypatch):
    import utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    captured = {}

    def fake_get(self, url, **kwargs):  # type: ignore[no-redef]
        captured["timeout"] = kwargs.get("timeout")

        class R:
            status_code = 200

            def json(self):
                return {}

            content = b""

        return R()

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)

    http_utils.http_get("https://example.com", timeout=5)
    assert captured.get("timeout") == 5


def test_shared_session_retry_configuration(monkeypatch):
    import utils.http_utils as http_utils
    from urllib3.util.retry import Retry

    http_utils._reset_shared_session_for_tests()
    session = http_utils.get_shared_session()
    https_adapter = session.adapters.get("https://")
    assert https_adapter is not None
    assert isinstance(getattr(https_adapter, "max_retries", None), Retry)
    retry: Retry = https_adapter.max_retries  # type: ignore[assignment]
    assert retry.backoff_factor == 0.0
    assert "GET" in (retry.allowed_methods or set())
    assert 503 in (retry.status_forcelist or set())


def test_shared_session_thread_isolation():
    import threading
    import requests
    import utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    # Same thread should reuse the session
    s1 = http_utils.get_shared_session()
    s2 = http_utils.get_shared_session()
    assert s1 is s2

    # Different threads should get distinct sessions
    other_session: list[requests.Session] = []

    def worker():
        other_session.append(http_utils.get_shared_session())

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert other_session, "worker thread failed to store session"
    assert s1 is not other_session[0]

from unittest.mock import Mock, patch

import pytest
from flask import Flask

from src.utils.http_utils import (
    APIError,
    json_error,
    json_internal_error,
    json_success,
    wants_json,
)


@pytest.fixture
def app():
    """Create a test Flask application."""
    app = Flask(__name__)
    return app


class TestAPIError:
    """Test cases for the APIError exception class."""

    def test_api_error_basic(self):
        """Test basic APIError creation."""
        error = APIError("Test error")
        assert error.message == "Test error"
        assert error.status == 400
        assert error.code is None
        assert error.details is None

    def test_api_error_with_all_params(self):
        """Test APIError with all parameters."""
        details = {"field": "test"}
        error = APIError("Test error", status=500, code="TEST_001", details=details)
        assert error.message == "Test error"
        assert error.status == 500
        assert error.code == "TEST_001"
        assert error.details == details

    def test_api_error_inheritance(self):
        """Test that APIError properly inherits from Exception."""
        error = APIError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"


class TestJsonError:
    """Test cases for the json_error function."""

    def test_json_error_basic(self, app):
        """Test basic json_error response."""
        with app.app_context():
            response, status = json_error("Test error")
            assert status == 400

            # Check response data
            response_data = response.get_json()
            assert response_data["error"] == "Test error"
            assert "code" not in response_data
            assert "details" not in response_data

    def test_json_error_includes_request_id_when_present(self, app, monkeypatch):
        """json_error should echo request_id if available via header/context."""
        with app.test_request_context("/", headers={"X-Request-Id": "abc-123"}):
            response, status = json_error("oops")
            assert status == 400
            data = response.get_json()
            assert data.get("error") == "oops"
            assert data.get("request_id") == "abc-123"


def test_http_get_timeout_tuple_from_env(monkeypatch):
    import requests
    import src.utils.http_utils as http_utils

    # Force split timeout tuple via module-level variables (evaluated at import)
    monkeypatch.setattr(http_utils, "CONNECT_TIMEOUT_SECONDS", 1.5, raising=True)
    monkeypatch.setattr(http_utils, "READ_TIMEOUT_SECONDS", 3.0, raising=True)

    http_utils._reset_shared_session_for_tests()

    captured = {}

    def fake_get(self, url, **kwargs):  # type: ignore[no-redef]
        captured["timeout"] = kwargs.get("timeout")

        class R:
            status_code = 200
            content = b"ok"

            def json(self):
                return {}

        return R()

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)

    http_utils.http_get("https://example.com")
    t = captured.get("timeout")
    assert isinstance(t, tuple) and t == (1.5, 3.0)


def test_http_get_latency_logging_success_and_failure(monkeypatch, caplog):
    import logging
    import requests
    import src.utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    # Enable latency logging
    monkeypatch.setenv("INKYPI_HTTP_LOG_LATENCY", "1")
    caplog.set_level(logging.INFO, logger=http_utils.__name__)

    # Success path
    def ok_get(self, url, **kwargs):  # type: ignore[no-redef]
        class R:
            status_code = 200
            content = b"x"

            def json(self):
                return {}

        return R()

    monkeypatch.setattr(requests.Session, "get", ok_get, raising=True)
    http_utils.http_get("https://example.com/success")
    assert any(
        "HTTP GET | url=https://example.com/success" in r.getMessage()
        for r in caplog.records
    )

    # Failure path
    def err_get(self, url, **kwargs):  # type: ignore[no-redef]
        raise requests.exceptions.ConnectionError("boom")

    caplog.clear()
    caplog.set_level(logging.WARNING, logger=http_utils.__name__)
    monkeypatch.setattr(requests.Session, "get", err_get, raising=True)
    try:
        http_utils.http_get("https://example.com/fail")
    except Exception:
        pass
    assert any(
        "HTTP GET failed | url=https://example.com/fail" in r.getMessage()
        for r in caplog.records
    )


def test_retry_backoff_env_configuration(monkeypatch):
    import src.utils.http_utils as http_utils

    # Override env-based values by monkeypatching the helper accessors indirectly
    monkeypatch.setenv("INKYPI_HTTP_RETRIES", "7")
    monkeypatch.setenv("INKYPI_HTTP_RETRIES_CONNECT", "5")
    monkeypatch.setenv("INKYPI_HTTP_RETRIES_READ", "6")
    monkeypatch.setenv("INKYPI_HTTP_RETRIES_STATUS", "4")
    monkeypatch.setenv("INKYPI_HTTP_BACKOFF", "0.25")

    # Force rebuild of session to pick up new retry config
    http_utils._reset_shared_session_for_tests()
    session = http_utils.get_shared_session()
    https_adapter = session.adapters.get("https://")
    assert https_adapter is not None
    retry = https_adapter.max_retries
    # Depending on type hints, retry may be Retry or int; ensure it's Retry-like
    from urllib3.util.retry import Retry

    assert isinstance(retry, Retry)
    assert retry.total == 7
    assert retry.connect == 5
    assert retry.read == 6
    assert retry.status == 4
    assert retry.backoff_factor == 0.25

    def test_json_error_with_code(self, app):
        """Test json_error with error code."""
        with app.app_context():
            response, status = json_error("Test error", code="TEST_001")
            response_data = response.get_json()
            assert response_data["error"] == "Test error"
            assert response_data["code"] == "TEST_001"

    def test_json_error_with_details(self, app):
        """Test json_error with details."""
        details = {"field": "username", "issue": "required"}
        with app.app_context():
            response, status = json_error("Validation error", details=details)
            response_data = response.get_json()
            assert response_data["error"] == "Validation error"
            assert response_data["details"] == details

    def test_json_error_custom_status(self, app):
        """Test json_error with custom HTTP status."""
        with app.app_context():
            response, status = json_error("Not found", status=404)
            assert status == 404
            response_data = response.get_json()
            assert response_data["error"] == "Not found"


class TestJsonInternalError:
    """Test cases for the json_internal_error function."""

    def test_json_internal_error_basic(self, app):
        """Test default json_internal_error response."""
        with app.app_context():
            response, status = json_internal_error("test context")
            assert status == 500
            response_data = response.get_json()
            assert response_data["error"] == "An internal error occurred"
            assert response_data["code"] == "internal_error"
            assert response_data["details"] == {"context": "test context"}

    def test_json_internal_error_with_details(self, app):
        """Test json_internal_error with additional details."""
        details = {"hint": "try again"}
        with app.app_context():
            response, status = json_internal_error("processing", details=details)
            assert status == 500
            response_data = response.get_json()
            assert response_data["error"] == "An internal error occurred"
            assert response_data["code"] == "internal_error"
            assert response_data["details"] == {"context": "processing", "hint": "try again"}

    def test_json_internal_error_custom_status_and_code(self, app):
        """Test custom status and error code propagation."""
        with app.app_context():
            response, status = json_internal_error(
                "db failure", status=503, code="DB_DOWN"
            )
            assert status == 503
            response_data = response.get_json()
            assert response_data["error"] == "An internal error occurred"
            assert response_data["code"] == "DB_DOWN"
            assert response_data["details"] == {"context": "db failure"}


class TestJsonSuccess:
    """Test cases for the json_success function."""

    def test_json_success_basic(self, app):
        """Test basic json_success response."""
        with app.app_context():
            response, status = json_success()
            assert status == 200
            response_data = response.get_json()
            assert response_data["success"] is True
            assert "message" not in response_data

    def test_json_success_with_message(self, app):
        """Test json_success with message."""
        with app.app_context():
            response, status = json_success("Operation completed")
            response_data = response.get_json()
            assert response_data["success"] is True
            assert response_data["message"] == "Operation completed"

    def test_json_success_with_payload(self, app):
        """Test json_success with additional payload data."""
        with app.app_context():
            response, status = json_success("Created", id=123, name="test")
            response_data = response.get_json()
            assert response_data["success"] is True
            assert response_data["message"] == "Created"
            assert response_data["id"] == 123
            assert response_data["name"] == "test"

    def test_json_success_custom_status(self, app):
        """Test json_success with custom status."""
        with app.app_context():
            response, status = json_success(status=201)
            assert status == 201


class TestWantsJson:
    """Test cases for the wants_json function."""

    def test_wants_json_api_path(self):
        """Test that API paths are detected as wanting JSON."""
        mock_request = Mock()
        mock_request.path = "/api/settings"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is True

    def test_wants_json_accept_header(self):
        """Test that JSON accept header is detected."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = True
        mock_request.accept_mimetypes.accept_html = False
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is True

    def test_wants_json_content_type(self):
        """Test that JSON content type is detected."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = True
        mock_request.get_json.return_value = {"test": "data"}

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is True

    def test_wants_json_false_for_html(self):
        """Test that HTML requests don't want JSON."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_false_for_unknown_path(self):
        """Test that unknown paths default to not wanting JSON."""
        mock_request = Mock()
        mock_request.path = "/unknown"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = False
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_exception_handling(self):
        """Test that exceptions are handled gracefully."""
        mock_request = Mock()
        mock_request.path = "/some/path"  # Use a path that won't trigger API detection
        # Simulate an exception in the entire request object
        mock_request.accept_mimetypes = Mock(side_effect=Exception("Test exception"))
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_with_provided_request(self):
        """Test wants_json with explicitly provided request object."""
        mock_request = Mock()
        mock_request.path = "/api/test"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        assert wants_json(mock_request) is True

    def test_wants_json_no_global_request(self):
        """Test wants_json when no global request exists."""
        mock_request = Mock()
        mock_request.path = "/api/test"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("src.utils.http_utils.request", None):
            assert wants_json(mock_request) is True

    def test_wants_json_get_json_exception_handling(self):
        """Test wants_json with exception in get_json."""
        mock_request = Mock()
        mock_request.path = "/test"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.side_effect = Exception("Test exception")

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_general_exception_handling(self):
        """Test wants_json with general exception in request processing."""
        mock_request = Mock()
        mock_request.path = "/test"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        # Simulate a general exception in the request object
        mock_request.configure_mock(
            **{
                "accept_mimetypes.accept_json": Mock(
                    side_effect=Exception("Test exception")
                )
            }
        )

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_outer_exception_handling(self):
        """Test wants_json with exception that triggers outer catch block."""

        # Create a mock request that raises an exception when accessing any attribute
        class ExceptionRequest:
            def __getattr__(self, name):
                raise Exception("Test outer exception")

        mock_request = ExceptionRequest()

        with patch("src.utils.http_utils.request", mock_request):
            assert wants_json() is False

from typing import Any

import pytest
import requests
from flask import Flask


def test_http_get_user_agent_and_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    import utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    captured = {}

    def fake_get(self, url: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        captured["headers"] = kwargs.get("headers")
        captured["timeout"] = kwargs.get("timeout")

        class R:
            status_code = 200

            def json(self) -> Any:
                return {}

            content = b""

        return R()

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)

    http_utils.http_get("https://example.com")

    assert isinstance(captured.get("headers"), dict)
    assert captured["headers"].get("User-Agent", "").startswith("InkyPi/")
    assert captured.get("timeout") == http_utils.DEFAULT_TIMEOUT_SECONDS


def test_http_get_timeout_override(monkeypatch: pytest.MonkeyPatch) -> Any:
    import utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    # Reset cache to ensure clean state
    try:
        from utils.http_cache import _reset_cache_for_tests

        _reset_cache_for_tests()
    except ImportError:
        pass

    captured = {}

    def fake_get(self, url: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        captured["timeout"] = kwargs.get("timeout")

        class R:
            status_code = 200

            def json(self) -> Any:
                return {}

            content = b""

        return R()

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)

    http_utils.http_get("https://example.com", timeout=5)
    assert captured.get("timeout") == 5


def test_shared_session_retry_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib3.util.retry import Retry

    import utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()
    session = http_utils.get_shared_session()
    https_adapter = session.adapters.get("https://")
    assert https_adapter is not None
    assert isinstance(getattr(https_adapter, "max_retries", None), Retry)
    retry: Retry = https_adapter.max_retries  # type: ignore[assignment]
    assert retry.backoff_factor == 0.0
    assert "GET" in (retry.allowed_methods or set())
    assert 503 in (retry.status_forcelist or set())


def test_shared_session_thread_isolation() -> None:
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

    def worker() -> None:
        other_session.append(http_utils.get_shared_session())

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert other_session, "worker thread failed to store session"
    assert s1 is not other_session[0]


from unittest.mock import Mock, patch  # noqa: E402

from utils.http_utils import (  # noqa: E402
    APIError,
    json_error,
    json_internal_error,
    json_success,
    reissue_json_error,
    wants_json,
)


@pytest.fixture
def app() -> Any:
    """Create a test Flask application."""
    return Flask(__name__)


class TestAPIError:
    """Test cases for the APIError exception class."""

    def test_api_error_basic(self) -> None:
        """Test basic APIError creation."""
        error = APIError("Test error")
        assert error.message == "Test error"
        assert error.status == 400
        assert error.code is None
        assert error.details is None

    def test_api_error_with_all_params(self) -> None:
        """Test APIError with all parameters."""
        details = {"field": "test"}
        error = APIError("Test error", status=500, code="TEST_001", details=details)
        assert error.message == "Test error"
        assert error.status == 500
        assert error.code == "TEST_001"
        assert error.details == details

    def test_api_error_inheritance(self) -> None:
        """Test that APIError properly inherits from Exception."""
        error = APIError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"


class TestJsonError:
    """Test cases for the json_error function."""

    def test_json_error_basic(self, app: Flask) -> None:
        """Test basic json_error response."""
        with app.app_context():
            response, status = json_error("Test error")
            assert status == 400

            # Check response data
            response_data = response.get_json()
            assert response_data["error"] == "Test error"
            assert "code" not in response_data
            assert "details" not in response_data

    def test_json_error_includes_request_id_when_present(
        self, app: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """json_error should echo request_id if available via header/context."""
        with app.test_request_context("/", headers={"X-Request-Id": "abc-123"}):
            response, status = json_error("oops")
            assert status == 400
            data = response.get_json()
            assert data.get("error") == "oops"
            assert data.get("request_id") == "abc-123"

    def test_reissue_json_error_uses_fallback_message(self, app: Flask) -> None:
        """reissue_json_error should ignore upstream error text."""
        with app.app_context():
            upstream, status = json_error(
                "tainted upstream text",
                status=422,
                code="validation_error",
                details={"field": "level"},
            )
            response, returned_status = reissue_json_error(
                (upstream, status), "safe fallback message"
            )

            assert returned_status == 422
            data = response.get_json()
            assert data["error"] == "safe fallback message"
            assert "code" not in data
            assert "details" not in data


def test_http_get_timeout_tuple_from_env(monkeypatch: pytest.MonkeyPatch) -> Any:
    import requests

    import utils.http_utils as http_utils

    # Force split timeout tuple via module-level variables (evaluated at import)
    monkeypatch.setattr(http_utils, "CONNECT_TIMEOUT_SECONDS", 1.5, raising=True)
    monkeypatch.setattr(http_utils, "READ_TIMEOUT_SECONDS", 3.0, raising=True)

    http_utils._reset_shared_session_for_tests()

    # Reset cache to ensure clean state
    try:
        from utils.http_cache import _reset_cache_for_tests

        _reset_cache_for_tests()
    except ImportError:
        pass

    captured = {}

    def fake_get(self, url: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        captured["timeout"] = kwargs.get("timeout")

        class R:
            status_code = 200
            content = b"ok"

            def json(self) -> Any:
                return {}

        return R()

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)

    http_utils.http_get("https://example.com")
    t = captured.get("timeout")
    assert isinstance(t, tuple) and t == (1.5, 3.0)


def test_http_get_latency_logging_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Any:
    import logging

    import requests

    import utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    # Enable latency logging
    monkeypatch.setenv("INKYPI_HTTP_LOG_LATENCY", "1")
    caplog.set_level(logging.INFO, logger=http_utils.__name__)

    # Success path
    def ok_get(self, url: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        class R:
            status_code = 200
            content = b"x"

            def json(self) -> Any:
                return {}

        return R()

    monkeypatch.setattr(requests.Session, "get", ok_get, raising=True)
    http_utils.http_get("https://example.com/success")
    assert any(
        "HTTP GET | url=https://example.com/success" in r.getMessage()
        for r in caplog.records
    )

    # Failure path
    def err_get(self, url: Any, **kwargs: Any) -> None:  # type: ignore[no-redef]
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


def test_retry_backoff_env_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    import utils.http_utils as http_utils

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

    def test_json_error_with_code(self, app: Flask) -> None:
        """Test json_error with error code."""
        with app.app_context():
            response, status = json_error("Test error", code="TEST_001")
            response_data = response.get_json()
            assert response_data["error"] == "Test error"
            assert response_data["code"] == "TEST_001"

    def test_json_error_with_details(self, app: Flask) -> None:
        """Test json_error with details."""
        details = {"field": "username", "issue": "required"}
        with app.app_context():
            response, status = json_error("Validation error", details=details)
            response_data = response.get_json()
            assert response_data["error"] == "Validation error"
            assert response_data["details"] == details

    def test_json_error_custom_status(self, app: Flask) -> None:
        """Test json_error with custom HTTP status."""
        with app.app_context():
            response, status = json_error("Not found", status=404)
            assert status == 404
            response_data = response.get_json()
            assert response_data["error"] == "Not found"


class TestJsonInternalError:
    """Test cases for the json_internal_error function."""

    def test_json_internal_error_basic(self, app: Flask) -> None:
        """Test default json_internal_error response."""
        with app.app_context():
            response, status = json_internal_error("test context")
            assert status == 500
            response_data = response.get_json()
            assert response_data["error"] == "An internal error occurred"
            assert response_data["code"] == "internal_error"
            assert response_data["details"] == {"context": "test context"}

    def test_json_internal_error_with_details(self, app: Flask) -> None:
        """Test json_internal_error with additional details."""
        details = {"hint": "try again"}
        with app.app_context():
            response, status = json_internal_error("processing", details=details)
            assert status == 500
            response_data = response.get_json()
            assert response_data["error"] == "An internal error occurred"
            assert response_data["code"] == "internal_error"
            assert response_data["details"] == {
                "context": "processing",
                "hint": "try again",
            }

    def test_json_internal_error_custom_status_and_code(self, app: Flask) -> None:
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

    def test_json_success_basic(self, app: Flask) -> None:
        """Test basic json_success response."""
        with app.app_context():
            response, status = json_success()
            assert status == 200
            response_data = response.get_json()
            assert response_data["success"] is True
            assert "message" not in response_data

    def test_json_success_with_message(self, app: Flask) -> None:
        """Test json_success with message."""
        with app.app_context():
            response, status = json_success("Operation completed")
            response_data = response.get_json()
            assert response_data["success"] is True
            assert response_data["message"] == "Operation completed"

    def test_json_success_with_payload(self, app: Flask) -> None:
        """Test json_success with additional payload data."""
        with app.app_context():
            response, status = json_success("Created", id=123, name="test")
            response_data = response.get_json()
            assert response_data["success"] is True
            assert response_data["message"] == "Created"
            assert response_data["id"] == 123
            assert response_data["name"] == "test"

    def test_json_success_custom_status(self, app: Flask) -> None:
        """Test json_success with custom status."""
        with app.app_context():
            response, status = json_success(status=201)
            assert status == 201


class TestWantsJson:
    """Test cases for the wants_json function."""

    def test_wants_json_api_path(self) -> None:
        """Test that API paths are detected as wanting JSON."""
        mock_request = Mock()
        mock_request.path = "/api/settings"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is True

    def test_wants_json_accept_header(self) -> None:
        """Test that JSON accept header is detected."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = True
        mock_request.accept_mimetypes.accept_html = False
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is True

    def test_wants_json_content_type(self) -> None:
        """Test that JSON content type is detected."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = True
        mock_request.get_json.return_value = {"test": "data"}

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is True

    def test_wants_json_false_for_html(self) -> None:
        """Test that HTML requests don't want JSON."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_false_for_unknown_path(self) -> None:
        """Test that unknown paths default to not wanting JSON."""
        mock_request = Mock()
        mock_request.path = "/unknown"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = False
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_exception_handling(self) -> None:
        """Test that exceptions are handled gracefully."""
        mock_request = Mock()
        mock_request.path = "/some/path"  # Use a path that won't trigger API detection
        # Simulate an exception in the entire request object
        mock_request.accept_mimetypes = Mock(side_effect=Exception("Test exception"))
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_with_provided_request(self) -> None:
        """Test wants_json with explicitly provided request object."""
        mock_request = Mock()
        mock_request.path = "/api/test"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        assert wants_json(mock_request) is True

    def test_wants_json_no_global_request(self) -> None:
        """Test wants_json when no global request exists."""
        mock_request = Mock()
        mock_request.path = "/api/test"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch("utils.http_utils.request", None):
            assert wants_json(mock_request) is True

    def test_wants_json_get_json_exception_handling(self) -> None:
        """Test wants_json with exception in get_json."""
        mock_request = Mock()
        mock_request.path = "/test"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.side_effect = Exception("Test exception")

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_general_exception_handling(self) -> None:
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

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is False

    def test_wants_json_outer_exception_handling(self) -> None:
        """Test wants_json with exception that triggers outer catch block."""

        # Create a mock request that raises an exception when accessing any attribute
        class ExceptionRequest:
            def __getattr__(self, name: Any) -> None:
                raise Exception("Test outer exception")

        mock_request = ExceptionRequest()

        with patch("utils.http_utils.request", mock_request):
            assert wants_json() is False


class TestRequestIdIsNotReflectedUnvalidated:
    """The inbound X-Request-Id is echoed into every json_* response body.

    An unvalidated header is client-controlled data reflected in a response —
    CodeQL py/reflective-xss, 95 pre-existing alerts across the codebase all
    tracing back to this one line.
    """

    def _request_id(self, flask_app: Any, header: str | None) -> Any:
        from utils.http_utils import json_success

        headers = {"X-Request-Id": header} if header is not None else {}
        with flask_app.test_request_context("/", headers=headers):
            body, _status = json_success("ok")
            return body.get_json().get("request_id")

    def test_a_well_formed_id_is_preserved(self, flask_app: Any) -> None:
        assert self._request_id(flask_app, "abc-123_XY.z:9") == "abc-123_XY.z:9"

    def test_a_uuid_is_preserved(self, flask_app: Any) -> None:
        rid = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        assert self._request_id(flask_app, rid) == rid

    @pytest.mark.parametrize(
        "header",
        [
            "<script>alert(1)</script>",
            "abc<img src=x onerror=alert(1)>",
            # A CRLF value is not tested here: werkzeug refuses to build such a
            # header at all, so header injection is already blocked upstream of
            # this code and the case cannot be represented.
            "a" * 129,
            "spaces are not ids",
        ],
    )
    def test_markup_and_oversized_values_are_replaced(
        self, flask_app: Any, header: str
    ) -> None:
        got = self._request_id(flask_app, header)
        assert got != header, "the header must not be echoed back verbatim"
        assert "<" not in got and ">" not in got and "\n" not in got
        # Replaced with a generated uuid rather than a cleaned-up version.
        assert len(got) == 36

    def test_absent_header_still_yields_an_id(self, flask_app: Any) -> None:
        assert self._request_id(flask_app, None)

    def test_a_valid_id_is_unchanged_by_the_escape(self, flask_app: Any) -> None:
        """The charset check runs first, so escaping must be a no-op here.

        If this ever fails, the accepted charset and the escape disagree and one
        of them is wrong.
        """
        for rid in ("abc-123_XY.z:9", "3f2504e0-4f89-11d3-9a0c-0305e82c3301"):
            assert self._request_id(flask_app, rid) == rid

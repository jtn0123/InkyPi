import pytest
from unittest.mock import Mock, patch
from flask import Flask, request, jsonify

from src.utils.http_utils import APIError, json_error, json_success, wants_json


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

        with patch('src.utils.http_utils.request', mock_request):
            assert wants_json() is True

    def test_wants_json_accept_header(self):
        """Test that JSON accept header is detected."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = True
        mock_request.accept_mimetypes.accept_html = False
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch('src.utils.http_utils.request', mock_request):
            assert wants_json() is True

    def test_wants_json_content_type(self):
        """Test that JSON content type is detected."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = True
        mock_request.get_json.return_value = {"test": "data"}

        with patch('src.utils.http_utils.request', mock_request):
            assert wants_json() is True

    def test_wants_json_false_for_html(self):
        """Test that HTML requests don't want JSON."""
        mock_request = Mock()
        mock_request.path = "/settings"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch('src.utils.http_utils.request', mock_request):
            assert wants_json() is False

    def test_wants_json_false_for_unknown_path(self):
        """Test that unknown paths default to not wanting JSON."""
        mock_request = Mock()
        mock_request.path = "/unknown"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = False
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch('src.utils.http_utils.request', mock_request):
            assert wants_json() is False

    def test_wants_json_exception_handling(self):
        """Test that exceptions are handled gracefully."""
        mock_request = Mock()
        mock_request.path = "/some/path"  # Use a path that won't trigger API detection
        # Simulate an exception in the entire request object
        mock_request.accept_mimetypes = Mock(side_effect=Exception("Test exception"))
        mock_request.is_json = False
        mock_request.get_json.return_value = None

        with patch('src.utils.http_utils.request', mock_request):
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

        with patch('src.utils.http_utils.request', None):
            assert wants_json(mock_request) is True

    def test_wants_json_get_json_exception_handling(self):
        """Test wants_json with exception in get_json."""
        mock_request = Mock()
        mock_request.path = "/test"
        mock_request.accept_mimetypes.accept_json = False
        mock_request.accept_mimetypes.accept_html = True
        mock_request.is_json = False
        mock_request.get_json.side_effect = Exception("Test exception")

        with patch('src.utils.http_utils.request', mock_request):
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
        mock_request.configure_mock(**{'accept_mimetypes.accept_json': Mock(side_effect=Exception("Test exception"))})

        with patch('src.utils.http_utils.request', mock_request):
            assert wants_json() is False

    def test_wants_json_outer_exception_handling(self):
        """Test wants_json with exception that triggers outer catch block."""
        # Create a mock request that raises an exception when accessing any attribute
        class ExceptionRequest:
            def __getattr__(self, name):
                raise Exception("Test outer exception")

        mock_request = ExceptionRequest()

        with patch('src.utils.http_utils.request', mock_request):
            assert wants_json() is False

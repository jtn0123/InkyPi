"""Unit tests for HTML-escaping of user-derived strings in json_error details.

Defense-in-depth: even if the frontend uses textContent today, any future
innerHTML slip would otherwise expose stored XSS.  (JTN-657)
"""

from __future__ import annotations

import pytest
from flask import Flask

from src.utils.http_utils import json_error


@pytest.fixture
def app():
    return Flask(__name__)


class TestJsonErrorDetailsEscape:
    """Verify that string values in the details dict are HTML-escaped."""

    def test_script_tag_escaped_in_details_string(self, app):
        """A bare <script> payload in a details value must have < and > escaped."""
        payload = "<script>alert(1)</script>"
        with app.app_context():
            response, status = json_error(
                "Validation failed",
                status=422,
                details={"field": payload},
            )
        data = response.get_json()
        assert status == 422
        field_value = data["details"]["field"]
        assert "<" not in field_value
        assert ">" not in field_value
        assert "&lt;" in field_value
        assert "&gt;" in field_value

    def test_nested_details_string_escaped(self, app):
        """String leaves inside nested dicts are escaped."""
        with app.app_context():
            response, _ = json_error(
                "err",
                details={"outer": {"inner": "<b>bold</b>"}},
            )
        data = response.get_json()
        assert "<b>" not in data["details"]["outer"]["inner"]
        assert "&lt;b&gt;" in data["details"]["outer"]["inner"]

    def test_list_details_strings_escaped(self, app):
        """Strings inside a list value are escaped."""
        with app.app_context():
            response, _ = json_error(
                "err",
                details={"errors": ["<bad>", "ok"]},
            )
        data = response.get_json()
        assert "<bad>" not in data["details"]["errors"][0]
        assert "&lt;bad&gt;" in data["details"]["errors"][0]
        assert data["details"]["errors"][1] == "ok"

    def test_non_string_values_unchanged(self, app):
        """Non-string scalars (int, bool, None) pass through without modification."""
        with app.app_context():
            response, _ = json_error(
                "err",
                details={"count": 3, "flag": True, "missing": None},
            )
        data = response.get_json()
        assert data["details"]["count"] == 3
        assert data["details"]["flag"] is True
        assert data["details"]["missing"] is None

    def test_ampersand_escaped(self, app):
        """Ampersands are HTML-escaped as well."""
        with app.app_context():
            response, _ = json_error(
                "err",
                details={"msg": "a & b"},
            )
        data = response.get_json()
        assert "&" not in data["details"]["msg"].replace("&amp;", "")
        assert "&amp;" in data["details"]["msg"]

    def test_none_details_omitted(self, app):
        """When details is None the key is absent from the response."""
        with app.app_context():
            response, _ = json_error("err", details=None)
        data = response.get_json()
        assert "details" not in data

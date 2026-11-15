"""The shared Gemini client keeps the API version the AI plugins rely on."""

from __future__ import annotations

from utils.google_ai import GOOGLE_AI_API_VERSION, google_ai_client


def test_client_is_pinned_to_v1beta_with_the_real_sdk() -> None:
    # google-genai 3.x defaults to "v1", which lacks some preview models.
    # Building a real client (no network call) proves the installed SDK
    # still accepts the option and applies it.
    client = google_ai_client("not-a-real-key")

    assert GOOGLE_AI_API_VERSION == "v1beta"
    assert client._api_client._http_options.api_version == "v1beta"

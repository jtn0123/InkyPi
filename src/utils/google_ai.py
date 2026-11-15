"""Build the Google Gemini client the AI plugins share."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.genai import Client

# google-genai 3.0 changed the Gemini Developer API default from ``v1beta``
# to ``v1``, and ``v1`` does not serve every preview model. AI Text offers
# the gemini-3*-preview models and AI Image writes its prompts with one, so
# keep the endpoint the plugins were built and tested against.
GOOGLE_AI_API_VERSION = "v1beta"


def google_ai_client(api_key: str) -> Client:
    """Return a Gemini Developer API client pinned to ``GOOGLE_AI_API_VERSION``."""
    # Imported here so the SDK only loads in the render worker that uses it.
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=GOOGLE_AI_API_VERSION),
    )

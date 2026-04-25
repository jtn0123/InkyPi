import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from openai import OpenAI
from PIL.Image import Image as ImageType

from plugins.base_plugin.base_plugin import (
    BasePlugin,
    validate_provider,
    validate_required_text,
)
from plugins.base_plugin.settings_schema import (
    callout,
    field,
    option,
    row,
    schema,
    section,
)

logger = logging.getLogger(__name__)


class AIText(BasePlugin):
    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Reject empty prompts and missing model at save time."""
        err: str | None = validate_required_text(settings, "textPrompt", "Prompt")
        if err:
            return err

        err = validate_required_text(settings, "textModel", "Text Model")
        if err:
            return err

        err = validate_provider(settings)
        if err:
            return err
        return None

    def build_settings_schema(self) -> dict[str, object]:
        schema_payload: dict[str, object] = schema(
            section(
                "Prompt",
                row(
                    field(
                        "title",
                        label="Title",
                        placeholder="Daily brief",
                        hint="Optional heading shown above the generated response.",
                    ),
                    field(
                        "provider",
                        "select",
                        label="Provider",
                        default="openai",
                        options=[
                            option("openai", "OpenAI"),
                            option("google", "Google"),
                        ],
                    ),
                ),
                row(
                    field(
                        "textModel",
                        "select",
                        label="Text Model",
                        default="gpt-5-nano",
                        options_source="provider",
                        options_source_default="openai",
                        # Pricing reference (update as providers publish new rates):
                        # OpenAI:  https://openai.com/api/pricing/
                        # Google:  https://ai.google.dev/gemini-api/docs/pricing
                        # Format:  "<name> \u00b7 $<in> in / $<out> out per 1M"
                        options_by_value={
                            "openai": [
                                option(
                                    "gpt-5.4",
                                    "GPT-5.4 \u00b7 $2.50 in / $10.00 out per 1M",
                                ),
                                option(
                                    "gpt-5-mini",
                                    "GPT-5 mini \u00b7 $0.30 in / $1.20 out per 1M",
                                ),
                                option(
                                    "gpt-5-nano",
                                    "GPT-5 nano \u00b7 $0.05 in / $0.20 out per 1M",
                                ),
                            ],
                            "google": [
                                option(
                                    "gemini-3.1-pro-preview",
                                    "Gemini 3.1 Pro \u00b7 $2.00 in / $8.00 out per 1M",
                                ),
                                option(
                                    "gemini-3-flash-preview",
                                    "Gemini 3 Flash \u00b7 $0.50 in / $2.00 out per 1M",
                                ),
                                option(
                                    "gemini-3.1-flash-lite-preview",
                                    "Gemini 3.1 Flash-Lite \u00b7 $0.25 in / $1.00 out per 1M",
                                ),
                            ],
                        },
                    )
                ),
                field(
                    "textPrompt",
                    "textarea",
                    label="Prompt",
                    placeholder="Summarize today's top AI news in 70 words.",
                    required=True,
                    rows=4,
                ),
                callout(
                    "Prices shown are approximate per 1M input / output tokens. "
                    "Output tokens are typically 3\u20134\u00d7 the input rate. "
                    "A typical response costs fractions of a cent."
                ),
            ),
        )
        return schema_payload

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        settings_template: dict[str, object] = template_params
        template_params["api_key"] = {
            "required": True,
            "services": [
                {"name": "OpenAI", "env_var": "OPEN_AI_SECRET"},
                {"name": "Google", "env_var": "GOOGLE_AI_SECRET"},
            ],
        }
        template_params["style_settings"] = True
        return settings_template

    def generate_image(
        self, settings: Mapping[str, object], device_config: Any
    ) -> ImageType:
        provider = settings.get("provider", "openai")
        if not isinstance(provider, str):
            provider = "openai"
        if not provider:
            provider = "openai"
        title = settings.get("title")
        if title is not None and not isinstance(title, str):
            title = None

        text_model = settings.get("textModel")
        if not isinstance(text_model, str) or not text_model:
            raise RuntimeError("Text Model is required.")

        text_prompt = settings.get("textPrompt", "")
        if not isinstance(text_prompt, str) or not text_prompt.strip():
            raise RuntimeError("Text Prompt is required.")

        try:
            if provider == "google":
                api_key = device_config.load_env_key("GOOGLE_AI_SECRET")
                if not api_key:
                    logger.error("Google AI API Key not configured")
                    raise RuntimeError("Google AI API Key not configured.")

                from google import genai

                google_client = genai.Client(api_key=api_key)
                prompt_response = AIText.fetch_text_prompt_google(
                    google_client, text_model, text_prompt
                )
            else:
                api_key = device_config.load_env_key("OPEN_AI_SECRET")
                if not api_key:
                    logger.error("OpenAI API Key not configured")
                    raise RuntimeError("OpenAI API Key not configured.")

                ai_client = OpenAI(api_key=api_key)
                prompt_response = AIText.fetch_text_prompt(
                    ai_client, text_model, text_prompt
                )
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Failed to make API request: {str(e)}")
            raise RuntimeError("API request failure, please check logs.") from e

        dimensions = self.get_oriented_dimensions(device_config)

        image_template_params: dict[str, object] = {
            "title": title,
            "content": prompt_response,
            "plugin_settings": settings,
        }

        return self.render_image(
            dimensions, "ai_text.html", "ai_text.css", image_template_params
        )

    @staticmethod
    def fetch_text_prompt(ai_client: Any, model: str, text_prompt: str) -> str:
        logger.info(
            f"Getting random text prompt from input {text_prompt}, model: {model}"
        )

        system_content = (
            "You are a highly intelligent text generation assistant. Generate concise, "
            "relevant, and accurate responses tailored to the user's input. The response "
            "should be 70 words or less."
            "IMPORTANT: Do not rephrase, reword, or provide an introduction. Respond directly "
            "to the request without adding explanations or extra context "
            "IMPORTANT: If the response naturally requires a newline for formatting, provide "
            "the '\\n' newline character explicitly for every new line. For regular sentences "
            "or paragraphs do not provide the new line character."
            f"For context, today is {datetime.now(tz=UTC).strftime('%Y-%m-%d')}"
        )
        user_content = text_prompt

        response = ai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=1,
        )

        prompt = str(response.choices[0].message.content or "")
        prompt = prompt.strip()
        logger.info(f"Generated random text prompt: {prompt}")
        return prompt

    @staticmethod
    def fetch_text_prompt_google(client: Any, model: str, text_prompt: str) -> str:
        """Fetch text response from Google Gemini API."""
        from google.genai import types

        logger.info(
            f"Getting text prompt from Google, input: {text_prompt}, model: {model}"
        )

        system_content = (
            "You are a highly intelligent text generation assistant. Generate concise, "
            "relevant, and accurate responses tailored to the user's input. The response "
            "should be 70 words or less."
            "IMPORTANT: Do not rephrase, reword, or provide an introduction. Respond directly "
            "to the request without adding explanations or extra context "
            "IMPORTANT: If the response naturally requires a newline for formatting, provide "
            "the '\\n' newline character explicitly for every new line. For regular sentences "
            "or paragraphs do not provide the new line character."
            f"For context, today is {datetime.now(tz=UTC).strftime('%Y-%m-%d')}"
        )

        response = client.models.generate_content(
            model=model,
            contents=text_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_content,
                temperature=1,
            ),
        )

        prompt = str(response.text or "")
        prompt = prompt.strip()
        logger.info(f"Generated text prompt via Google: {prompt}")
        return prompt

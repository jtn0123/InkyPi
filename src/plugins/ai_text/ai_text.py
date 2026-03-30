import logging
from datetime import datetime

from openai import OpenAI

from plugins.base_plugin.base_plugin import BasePlugin
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
    def build_settings_schema(self):
        return schema(
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
                        options_by_value={
                            "openai": [
                                option("gpt-5.4", "GPT-5.4 \u00b7 $2.50/1M in"),
                                option("gpt-5-mini", "GPT-5 mini \u00b7 ~$0.30/1M in"),
                                option("gpt-5-nano", "GPT-5 nano \u00b7 $0.05/1M in"),
                            ],
                            "google": [
                                option(
                                    "gemini-3.1-pro-preview",
                                    "Gemini 3.1 Pro \u00b7 ~$2.00/1M in",
                                ),
                                option(
                                    "gemini-3-flash-preview",
                                    "Gemini 3 Flash \u00b7 $0.50/1M in",
                                ),
                                option(
                                    "gemini-3.1-flash-lite-preview",
                                    "Gemini 3.1 Flash-Lite \u00b7 $0.25/1M in",
                                ),
                            ],
                        },
                    ),
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
                    "Prices shown are approximate per 1M input tokens. "
                    "A typical response costs fractions of a cent."
                ),
            )
        )

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "OpenAI / Google",
            "expected_key": "OPEN_AI_SECRET",
            "alt_key": "GOOGLE_AI_SECRET",
        }
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        provider = settings.get("provider", "openai")
        title = settings.get("title")

        text_model = settings.get("textModel")
        if not text_model:
            raise RuntimeError("Text Model is required.")

        text_prompt = settings.get("textPrompt", "")
        if not text_prompt.strip():
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

        image_template_params = {
            "title": title,
            "content": prompt_response,
            "plugin_settings": settings,
        }

        image = self.render_image(
            dimensions, "ai_text.html", "ai_text.css", image_template_params
        )

        return image

    @staticmethod
    def fetch_text_prompt(ai_client, model, text_prompt):
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
            f"For context, today is {datetime.today().strftime('%Y-%m-%d')}"
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

        prompt = response.choices[0].message.content.strip()
        logger.info(f"Generated random text prompt: {prompt}")
        return prompt

    @staticmethod
    def fetch_text_prompt_google(client, model, text_prompt):
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
            f"For context, today is {datetime.today().strftime('%Y-%m-%d')}"
        )

        response = client.models.generate_content(
            model=model,
            contents=text_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_content,
                temperature=1,
            ),
        )

        prompt = response.text.strip()
        logger.info(f"Generated text prompt via Google: {prompt}")
        return prompt

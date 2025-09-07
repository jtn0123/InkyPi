import logging
from datetime import datetime

from openai import OpenAI

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class AIText(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "OpenAI",
            "expected_key": "OPEN_AI_SECRET",
        }
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        api_key = device_config.load_env_key("OPEN_AI_SECRET")
        if not api_key:
            raise RuntimeError("OPEN AI API Key not configured.")

        title = settings.get("title")

        text_model = settings.get("textModel")
        if not text_model:
            raise RuntimeError("Text Model is required.")

        text_prompt = settings.get("textPrompt", "")
        if not text_prompt.strip():
            raise RuntimeError("Text Prompt is required.")

        try:
            ai_client = OpenAI(api_key=api_key)
            # Map optional creativity level (0..1) to temperature with sensible defaults
            creativity = settings.get("creativity")
            temperature = None
            if isinstance(creativity, str) and creativity.strip():
                try:
                    val = float(creativity)
                    temperature = max(0.0, min(1.5, val))
                except Exception:
                    temperature = None
            prompt_response = AIText.fetch_text_prompt(
                ai_client, text_model, text_prompt, temperature=temperature
            )
        except Exception as e:
            logger.error(f"Failed to make Open AI request: {str(e)}")
            raise RuntimeError("Open AI request failure, please check logs.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

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
    def fetch_text_prompt(ai_client, model, text_prompt, temperature: float | None = None):
        logger.info(
            f"Getting random text prompt from input {text_prompt}, model: {model}"
        )

        system_content = (
            "You are a creative, vivid, and succinct writing assistant for an e-ink display. "
            "Produce a compact, evocative response (≤70 words) tailored to the user's input. "
            "Favor strong imagery, metaphor, or wit without being verbose. Avoid hedging. "
            "Do NOT add prefaces or explanations; respond directly. If formatting needs lines, use '\n'. "
            "No emojis, no markdown, no lists. Keep language clear, bold, and readable at a glance. "
            f"For context, today is {datetime.today().strftime('%Y-%m-%d')}"
        )
        user_content = text_prompt

        # Make the API call
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
        }
        # Default slightly elevated creativity if not provided
        if temperature is None:
            kwargs["temperature"] = 1.1
        else:
            kwargs["temperature"] = temperature

        response = ai_client.chat.completions.create(**kwargs)

        prompt = response.choices[0].message.content.strip()
        logger.info(f"Generated random text prompt: {prompt}")
        return prompt

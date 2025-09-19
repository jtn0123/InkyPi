import logging
from io import BytesIO

import requests
from openai import OpenAI
from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
import utils.http_utils as http_utils
from utils.progress import record_step
from time import perf_counter

logger = logging.getLogger(__name__)

IMAGE_MODELS = ["dall-e-3", "dall-e-2", "gpt-image-1"]
DEFAULT_IMAGE_MODEL = "dall-e-3"
DEFAULT_IMAGE_QUALITY = "standard"


class AIImage(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "OpenAI",
            "expected_key": "OPEN_AI_SECRET",
        }
        return template_params

    def generate_image(self, settings, device_config):

        api_key = device_config.load_env_key("OPEN_AI_SECRET")
        if not api_key:
            raise RuntimeError("OPEN AI API Key not configured.")

        text_prompt = settings.get("textPrompt", "")

        image_model = settings.get("imageModel", DEFAULT_IMAGE_MODEL)
        if image_model not in IMAGE_MODELS:
            raise RuntimeError("Invalid Image Model provided.")
        # Default to 'standard' for all models; mapping handled in fetch_image
        image_quality = settings.get("quality", DEFAULT_IMAGE_QUALITY)
        randomize_prompt = settings.get("randomizePrompt") == "true"

        image = None
        try:
            ai_client = OpenAI(api_key=api_key)
            if randomize_prompt:
                text_prompt = AIImage.fetch_image_prompt(ai_client, text_prompt)

            # Sanitize prompt before sending to image generation
            text_prompt = AIImage.sanitize_prompt(text_prompt)

            image = AIImage.fetch_image(
                ai_client,
                text_prompt,
                model=image_model,
                quality=image_quality,
                orientation=device_config.get_config("orientation"),
            )
        except Exception as e:
            logger.error(f"Failed to make Open AI request: {str(e)}")
            raise RuntimeError("Open AI request failure, please check logs.")
        return image

    @staticmethod
    def fetch_image(
        ai_client,
        prompt,
        model="dalle-e-3",
        quality="standard",
        orientation="horizontal",
    ):
        logger.info(
            f"Generating image for prompt: {prompt}, model: {model}, quality: {quality}"
        )
        prompt += (
            ". The image should fully occupy the entire canvas without any frames, "
            "borders, or cropped areas. No blank spaces or artificial framing."
        )
        prompt += (
            "Focus on simplicity, bold shapes, and strong contrast to enhance clarity "
            "and visual appeal. Avoid excessive detail or complex gradients, ensuring "
            "the design works well with flat, vibrant colors."
        )

        def normalize_quality(model: str, requested: str):
            # Map UI values to API-supported values per model
            req = (requested or "").lower()
            if model == "dall-e-3":
                # Allowed: 'standard' | 'hd'
                if req in ("hd", "high"):
                    return "hd"
                return "standard"
            if model == "gpt-image-1":
                # Allowed: 'low' | 'medium' | 'high' | 'auto'
                if req in ("low", "medium", "high", "auto"):
                    return req
                # Back-compat: map 'standard' (old value) to 'medium'
                if req in ("standard", ""):
                    return "medium"
                # Fallback to a sensible default
                return "medium"
            # dall-e-2: no quality parameter
            return None

        args = {
            "model": model,
            "prompt": prompt,
            "size": "1024x1024",
        }
        if model == "dall-e-3":
            args["size"] = "1792x1024" if orientation == "horizontal" else "1024x1792"
            q = normalize_quality(model, quality)
            if q:
                args["quality"] = q
        elif model == "gpt-image-1":
            args["size"] = "1536x1024" if orientation == "horizontal" else "1024x1536"
            q = normalize_quality(model, quality)
            if q:
                args["quality"] = q

        # Try image generation; if policy violation occurs, retry once with a safe fallback prompt
        try:
            _t_provider_gen = perf_counter()
            response = ai_client.images.generate(**args)
            try:
                record_step("provider_generate")
            except Exception:
                pass
            try:
                logger.info(
                    "AI provider generate elapsed_ms=%s",
                    int((perf_counter() - _t_provider_gen) * 1000),
                )
            except Exception:
                pass
        except Exception as e:
            if "content_policy_violation" in str(e):
                logger.warning(
                    "OpenAI content policy violation detected; retrying with a safe fallback prompt."
                )
                safe_prompt = AIImage.build_safe_fallback_prompt()
                # Preserve sizing/quality args but replace only the prompt
                args["prompt"] = safe_prompt
                response = ai_client.images.generate(**args)
            else:
                raise
        # The OpenAI image response may provide either a URL or a base64 payload
        data0 = response.data[0]
        image_url = getattr(data0, "url", None)
        b64_payload = getattr(data0, "b64_json", None)

        if image_url:
            # Download the generated image using centralized HTTP helper
            _t_download = perf_counter()
            resp = http_utils.http_get(image_url, timeout=30)
            # Respect raise_for_status if available; MagicMocks in tests will no-op
            raise_for_status = getattr(resp, "raise_for_status", None)
            if callable(raise_for_status):
                raise_for_status()
            content_bytes = resp.content
            try:
                record_step("provider_download")
            except Exception:
                pass
            try:
                logger.info(
                    "AI image download elapsed_ms=%s bytes=%s",
                    int((perf_counter() - _t_download) * 1000),
                    len(content_bytes),
                )
            except Exception:
                pass
        elif b64_payload:
            # Decode inline base64 payload returned by some OpenAI clients
            import base64

            try:
                content_bytes = base64.b64decode(b64_payload)
            except Exception as e:
                logger.exception("Failed to decode base64 image payload")
                raise RuntimeError("Failed to decode AI image bytes") from e
        else:
            logger.error("AI image response did not contain 'url' or 'b64_json'")
            raise RuntimeError("OpenAI image response missing image data")

        from utils.image_utils import load_image_from_bytes
        _t_decode = perf_counter()
        img = load_image_from_bytes(content_bytes, image_open=Image.open)
        if img is None:
            raise RuntimeError("Failed to decode AI image bytes")
        try:
            record_step("provider_decode")
        except Exception:
            pass
        try:
            logger.info(
                "AI image decode elapsed_ms=%s",
                int((perf_counter() - _t_decode) * 1000),
            )
        except Exception:
            pass
        return img

    @staticmethod
    def fetch_image_prompt(ai_client, from_prompt=None):
        logger.info("Getting random image prompt...")

        system_content = (
            "You are a creative assistant generating extremely random and unique image prompts. "
            "Avoid common themes. Focus on unexpected, unconventional, and bizarre combinations "
            "of art style, medium, subjects, time periods, and moods. No repetition. Keep prompts "
            "20 words or less. IMPORTANT: Do NOT reference living artists, copyrighted IP, brands, "
            "logos, trademarks, or celebrities. Avoid phrases like 'in the style of' or 'by <name>'. "
            "Do not include text to render. Provide only the prompt."
        )
        user_content = (
            "Give me a completely random image prompt, something unexpected and creative! "
            "Let's see what your AI mind can cook up!"
        )
        if from_prompt and from_prompt.strip():
            system_content = (
                "You are a creative assistant specializing in generating highly descriptive "
                "and unique prompts for creating images. Rewrite short prompts to make them more "
                "imaginative while staying true to the original idea. Avoid irrelevant details. "
                "Avoid common themes. Focus on unexpected, unconventional, and bizarre combinations "
                "of art style, medium, subjects, time periods, and moods. Keep it 20 words or less. "
                "IMPORTANT: Do NOT reference living artists, copyrighted IP, brands, logos, trademarks, "
                "or celebrities. Avoid phrases like 'in the style of' or 'by <name>'. Do not include text."
            )
            user_content = (
                f'Original prompt: "{from_prompt}"\n'
                "Rewrite it to make it more detailed, imaginative, and unique while staying "
                "true to the original idea. Include vivid imagery and descriptive details. "
                "Avoid changing the subject of the prompt."
            )

        # Make the API call
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=1,
        )

        prompt = response.choices[0].message.content.strip()
        logger.info(f"Generated random image prompt: {prompt}")
        return prompt

    @staticmethod
    def build_safe_fallback_prompt() -> str:
        """Return a conservative, policy-safe prompt suitable for an e-ink display.

        This is used when OpenAI rejects the original prompt due to content policy.
        """
        base = (
            "Abstract high-contrast geometric composition with bold shapes and clean minimal lines, "
            "no text, no logos, safe content."
        )
        base += (
            " The image should fully occupy the entire canvas without any frames, borders, or cropped "
            "areas. No blank spaces or artificial framing."
        )
        base += (
            " Focus on simplicity, bold shapes, and strong contrast to enhance clarity and visual appeal. "
            "Avoid excessive detail or complex gradients, ensuring the design works well with flat, vibrant colors."
        )
        return base

    @staticmethod
    def sanitize_prompt(prompt: str) -> str:
        """Remove risky phrases and references that commonly trigger policy blocks.

        - Drops 'in the style of' and 'by <name>' patterns
        - Removes explicit brand/logo/trademark words
        - Trims length to a reasonable limit for safety
        """
        try:
            import re

            cleaned = prompt or ""
            # Remove common style-copy patterns
            cleaned = re.sub(r"in\s+the\s+style\s+of\s+[^,.]+", "", cleaned, flags=re.I)
            cleaned = re.sub(r"by\s+[A-Z][a-zA-Z\-\s]+", "", cleaned)

            # Remove brand/logo/trademark words (lightweight and conservative)
            banned = [
                "logo", "trademark", "brand", "copyright", "celebrity",
                "Disney", "Marvel", "DC Comics", "Nintendo", "Pokemon",
                "Star Wars", "Harry Potter", "Pixar", "Coca-Cola", "Apple",
            ]
            pattern = re.compile(r"|".join(re.escape(w) for w in banned), re.I)
            cleaned = pattern.sub("", cleaned)

            # Normalize whitespace and limit length
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if len(cleaned) > 200:
                cleaned = cleaned[:200].rstrip()
            return cleaned
        except Exception:
            return prompt

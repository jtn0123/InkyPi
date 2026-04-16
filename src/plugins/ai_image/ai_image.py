import base64
import logging
from io import BytesIO

from openai import OpenAI

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

OPENAI_IMAGE_MODEL = "gpt-image-1.5"
GOOGLE_IMAGE_MODEL = "imagen-4.0-generate-001"

IMAGE_MODELS_BY_PROVIDER = {
    "openai": (OPENAI_IMAGE_MODEL,),
    "google": (GOOGLE_IMAGE_MODEL,),
}
IMAGE_MODELS = [
    model
    for provider_models in IMAGE_MODELS_BY_PROVIDER.values()
    for model in provider_models
]
DEFAULT_IMAGE_MODEL = OPENAI_IMAGE_MODEL
DEFAULT_IMAGE_QUALITY = "medium"


class AIImage(BasePlugin):
    def validate_settings(self, settings: dict) -> str | None:
        """Reject empty prompts at save time so bad input does not persist."""
        if err := validate_required_text(settings, "textPrompt", "Prompt"):
            return err
        if err := validate_provider(settings):
            return err

        provider = settings.get("provider", "openai")
        model = (settings.get("imageModel") or DEFAULT_IMAGE_MODEL).strip()
        if model not in IMAGE_MODELS_BY_PROVIDER[provider]:
            return f"Invalid image model for provider {provider}: {model!r}"

        return None

    def build_settings_schema(self):
        return schema(
            section(
                "Prompt",
                field(
                    "textPrompt",
                    "textarea",
                    label="Prompt",
                    placeholder="A surreal breakfast floating through a neon sky.",
                    required=True,
                    rows=4,
                ),
                field(
                    "randomizePrompt",
                    "checkbox",
                    label="Randomize Prompt",
                    hint="Use the current prompt as a seed and let the model remix it before generating the image.",
                    submit_unchecked=True,
                    checked_value="true",
                    unchecked_value="false",
                ),
            ),
            section(
                "Generation",
                row(
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
                    field(
                        "imageModel",
                        "select",
                        label="Image Model",
                        default=DEFAULT_IMAGE_MODEL,
                        options_source="provider",
                        options_source_default="openai",
                        options_by_value={
                            "openai": [
                                option(
                                    DEFAULT_IMAGE_MODEL,
                                    "GPT Image 1.5 \u00b7 ~$0.07/img",
                                ),
                            ],
                            "google": [
                                option(
                                    GOOGLE_IMAGE_MODEL,
                                    "Imagen 4 \u00b7 ~$0.04/img",
                                ),
                            ],
                        },
                    ),
                ),
                row(
                    field(
                        "quality",
                        "select",
                        label="Quality",
                        default=DEFAULT_IMAGE_QUALITY,
                        options_source="imageModel",
                        options_source_default=DEFAULT_IMAGE_MODEL,
                        options_by_value={
                            DEFAULT_IMAGE_MODEL: [
                                option("high", "High (~$0.20)"),
                                option("medium", "Medium (~$0.07)"),
                                option("low", "Low (~$0.01)"),
                            ],
                            GOOGLE_IMAGE_MODEL: [
                                option("standard", "Standard"),
                            ],
                        },
                    ),
                ),
                callout(
                    "Prices are approximate per image at default resolution and may change. "
                    "See provider pricing pages for current rates."
                ),
            ),
        )

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "OpenAI / Google",
            "expected_key": "OPEN_AI_SECRET",
            "alt_key": "GOOGLE_AI_SECRET",
        }
        return template_params

    def _validate_generate_inputs(self, settings, provider):
        image_model = (settings.get("imageModel") or DEFAULT_IMAGE_MODEL).strip()
        allowed_models = IMAGE_MODELS_BY_PROVIDER.get(provider)
        if not allowed_models:
            logger.error(f"Invalid provider for AI image plugin: {provider}")
            raise RuntimeError("Invalid provider provided.")
        if image_model not in allowed_models:
            logger.error(
                "Invalid image model %s for provider %s",
                image_model,
                provider,
            )
            raise RuntimeError("Invalid Image Model provided.")
        return image_model, settings.get("quality", DEFAULT_IMAGE_QUALITY)

    def _maybe_randomize_google_prompt(
        self, google_client, text_prompt, randomize_prompt
    ):
        if not randomize_prompt:
            return text_prompt
        logger.debug("Generating randomized prompt using Gemini...")
        randomized = AIImage.fetch_image_prompt_google(google_client, text_prompt)
        logger.info(f"Randomized prompt: '{randomized}'")
        return randomized

    def _maybe_randomize_openai_prompt(self, ai_client, text_prompt, randomize_prompt):
        if not randomize_prompt:
            return text_prompt
        logger.debug("Generating randomized prompt using GPT...")
        randomized = AIImage.fetch_image_prompt(ai_client, text_prompt)
        logger.info(f"Randomized prompt: '{randomized}'")
        return randomized

    def _generate_google_image(
        self, device_config, text_prompt, image_model, randomize
    ):
        api_key = device_config.load_env_key("GOOGLE_AI_SECRET")
        if not api_key:
            logger.error("Google AI API Key not configured")
            raise RuntimeError("Google AI API Key not configured.")

        from google import genai

        google_client = genai.Client(api_key=api_key)
        prompt = self._maybe_randomize_google_prompt(
            google_client, text_prompt, randomize
        )
        logger.info(f"Generating image with {image_model}...")
        return self.fetch_image_google(google_client, prompt, image_model)

    def _generate_openai_image(
        self,
        device_config,
        text_prompt,
        image_model,
        image_quality,
        orientation,
        randomize,
    ):
        api_key = device_config.load_env_key("OPEN_AI_SECRET")
        if not api_key:
            logger.error("OpenAI API Key not configured")
            raise RuntimeError("OpenAI API Key not configured.")

        ai_client = OpenAI(api_key=api_key)
        prompt = self._maybe_randomize_openai_prompt(ai_client, text_prompt, randomize)
        logger.info(f"Generating image with {image_model}...")
        return self.fetch_image(
            ai_client,
            prompt,
            model=image_model,
            quality=image_quality,
            orientation=orientation,
        )

    def generate_image(self, settings, device_config):
        logger.info("=== AI Image Plugin: Starting image generation ===")

        provider = settings.get("provider", "openai")
        text_prompt = settings.get("textPrompt", "")
        image_model, image_quality = self._validate_generate_inputs(settings, provider)
        randomize_prompt = settings.get("randomizePrompt") == "true"
        orientation = device_config.get_config("orientation")

        logger.info(
            f"Settings: provider={provider}, model={image_model}, quality={image_quality}, orientation={orientation}"
        )

        image = None
        try:
            if provider == "google":
                image = self._generate_google_image(
                    device_config,
                    text_prompt,
                    image_model,
                    randomize_prompt,
                )
            else:
                image = self._generate_openai_image(
                    device_config,
                    text_prompt,
                    image_model,
                    image_quality,
                    orientation,
                    randomize_prompt,
                )

            if image:
                logger.info(
                    f"AI image generated successfully: {image.size[0]}x{image.size[1]}"
                )
            else:
                logger.error("Image generation completed without returning an image")
                raise RuntimeError("Failed to generate image")

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Failed to make API request: {str(e)}")
            raise RuntimeError("API request failure, please check logs.") from e

        logger.info("=== AI Image Plugin: Image generation complete ===")
        return image

    def fetch_image(
        self,
        ai_client,
        prompt,
        model=DEFAULT_IMAGE_MODEL,
        quality="medium",
        orientation="horizontal",
    ):
        """Fetch image from OpenAI API."""
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

        # Normalize quality
        quality_lower = str(quality).lower() if quality else ""
        if quality_lower in ["low", "medium", "high", "auto"]:
            image_quality = quality_lower
        else:
            image_quality = "medium"

        args = {
            "model": model,
            "prompt": prompt,
            "size": "1536x1024" if orientation == "horizontal" else "1024x1536",
            "quality": image_quality,
        }

        response = ai_client.images.generate(**args)
        image_base64 = response.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        image = self.image_loader.from_bytesio(
            BytesIO(image_bytes), (1536, 1536), resize=False
        )
        if image is None:
            raise RuntimeError("Failed to decode generated image")
        return image

    def fetch_image_google(self, client, prompt, model):
        """Fetch image from Google Imagen API."""
        from google.genai import types

        logger.info(f"Generating Google image for prompt: {prompt}, model: {model}")
        prompt += (
            ". The image should fully occupy the entire canvas without any frames, "
            "borders, or cropped areas. No blank spaces or artificial framing."
        )
        prompt += (
            "Focus on simplicity, bold shapes, and strong contrast to enhance clarity "
            "and visual appeal. Avoid excessive detail or complex gradients, ensuring "
            "the design works well with flat, vibrant colors."
        )

        config = types.GenerateImagesConfig(number_of_images=1)
        response = client.models.generate_images(
            model=model,
            prompt=prompt,
            config=config,
        )
        if not response.generated_images:
            raise RuntimeError("Google Imagen returned no images")
        image = self.image_loader.from_bytesio(
            BytesIO(response.generated_images[0].image.image_bytes),
            (1536, 1536),
            resize=False,
        )
        if image is None:
            raise RuntimeError("Failed to decode generated image")
        return image

    @staticmethod
    def fetch_image_prompt(ai_client, from_prompt=None):
        logger.info("Getting random image prompt...")

        system_content = (
            "You are a creative assistant generating extremely random and unique image prompts. "
            "Avoid common themes. Focus on unexpected, unconventional, and bizarre combinations "
            "of art style, medium, subjects, time periods, and moods. No repetition. Prompts "
            "should be 20 words or less and specify random artist, movie, tv show or time period "
            "for the theme. Do not provide any headers or repeat the request, just provide the "
            "updated prompt in your response."
        )
        user_content = (
            "Give me a completely random image prompt, something unexpected and creative! "
            "Let's see what your AI mind can cook up!"
        )
        if from_prompt and from_prompt.strip():
            system_content = (
                "You are a creative assistant specializing in generating highly descriptive "
                "and unique prompts for creating images. When given a short or simple image "
                "description, your job is to rewrite it into a more detailed, imaginative, "
                "and descriptive version that captures the essence of the original while "
                "making it unique and vivid. Avoid adding irrelevant details but feel free "
                "to include creative and visual enhancements. Avoid common themes. Focus on "
                "unexpected, unconventional, and bizarre combinations of art style, medium, "
                "subjects, time periods, and moods. Do not provide any headers or repeat the "
                "request, just provide your updated prompt in the response. Prompts "
                "should be 20 words or less and specify random artist, movie, tv show or time "
                "period for the theme."
            )
            user_content = (
                f'Original prompt: "{from_prompt}"\n'
                "Rewrite it to make it more detailed, imaginative, and unique while staying "
                "true to the original idea. Include vivid imagery and descriptive details. "
                "Avoid changing the subject of the prompt."
            )

        response = ai_client.chat.completions.create(
            model="gpt-5-nano",
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
    def fetch_image_prompt_google(client, from_prompt=None):
        """Use Gemini to remix a prompt before generating an image."""
        from google.genai import types

        logger.info("Getting random image prompt via Gemini...")

        system_content = (
            "You are a creative assistant generating extremely random and unique image prompts. "
            "Avoid common themes. Focus on unexpected, unconventional, and bizarre combinations "
            "of art style, medium, subjects, time periods, and moods. No repetition. Prompts "
            "should be 20 words or less and specify random artist, movie, tv show or time period "
            "for the theme. Do not provide any headers or repeat the request, just provide the "
            "updated prompt in your response."
        )
        user_content = (
            "Give me a completely random image prompt, something unexpected and creative! "
            "Let's see what your AI mind can cook up!"
        )
        if from_prompt and from_prompt.strip():
            system_content = (
                "You are a creative assistant specializing in generating highly descriptive "
                "and unique prompts for creating images. When given a short or simple image "
                "description, your job is to rewrite it into a more detailed, imaginative, "
                "and descriptive version that captures the essence of the original while "
                "making it unique and vivid. Avoid adding irrelevant details but feel free "
                "to include creative and visual enhancements. Avoid common themes. Focus on "
                "unexpected, unconventional, and bizarre combinations of art style, medium, "
                "subjects, time periods, and moods. Do not provide any headers or repeat the "
                "request, just provide your updated prompt in the response. Prompts "
                "should be 20 words or less and specify random artist, movie, tv show or time "
                "period for the theme."
            )
            user_content = (
                f'Original prompt: "{from_prompt}"\n'
                "Rewrite it to make it more detailed, imaginative, and unique while staying "
                "true to the original idea. Include vivid imagery and descriptive details. "
                "Avoid changing the subject of the prompt."
            )

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_content,
                temperature=1,
            ),
        )

        prompt = response.text.strip()
        logger.info(f"Generated random image prompt via Gemini: {prompt}")
        return prompt

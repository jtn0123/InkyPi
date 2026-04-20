import logging
from random import choice

from PIL import Image, ImageColor, ImageOps

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import field, option, row, schema, section
from utils.http_client import get_http_session
from utils.http_utils import pinned_dns
from utils.image_utils import pad_image_blur
from utils.plugin_errors import PermanentPluginError
from utils.security_utils import validate_url_with_ips

logger = logging.getLogger(__name__)


class ImmichProvider:
    def __init__(
        self,
        base_url: str,
        key: str,
        image_loader,
        pinned_ips: tuple[str, ...] | None = None,
    ):
        self.base_url = base_url
        self.key = key
        self.headers = {"x-api-key": self.key}
        self.image_loader = image_loader
        self.session = get_http_session()
        self.pinned_ips: tuple[str, ...] = tuple(pinned_ips or ())
        import urllib.parse as _urlparse

        self._pin_hostname = _urlparse.urlparse(base_url).hostname or ""

    def _pin(self):
        """Context manager that pins DNS to the validated IPs for this base URL."""
        return pinned_dns(self._pin_hostname, self.pinned_ips)

    def get_album_id(self, album: str) -> str:
        logger.debug(f"Fetching albums from {self.base_url}")
        with self._pin():
            r = self.session.get(
                f"{self.base_url}/api/albums", headers=self.headers, timeout=10
            )
        r.raise_for_status()
        albums = r.json()

        matching_albums = [a for a in albums if a["albumName"] == album]
        if not matching_albums:
            raise RuntimeError(f"Album '{album}' not found.")

        return matching_albums[0]["id"]

    def get_assets(self, album_id: str) -> list[dict]:
        """Fetch all assets from album."""
        all_items = []
        page_items = [1]
        page = 1

        logger.debug(f"Fetching assets from album {album_id}")
        while page_items:
            body = {"albumIds": [album_id], "size": 1000, "page": page}
            with self._pin():
                r2 = self.session.post(
                    f"{self.base_url}/api/search/metadata",
                    json=body,
                    headers=self.headers,
                    timeout=10,
                )
            r2.raise_for_status()
            assets_data = r2.json()

            page_items = assets_data.get("assets", {}).get("items", [])
            all_items.extend(page_items)
            page += 1

        logger.debug(f"Found {len(all_items)} total assets in album")
        return all_items

    def get_image(
        self, album: str, dimensions: tuple[int, int], resize: bool = True
    ) -> Image.Image | None:
        """
        Get a random image from the album.

        Args:
            album: Album name
            dimensions: Target dimensions (width, height)
            resize: Whether to let loader resize (False when padding will be applied)

        Returns:
            PIL Image or None on error
        """
        try:
            logger.info(f"Getting id for album '{album}'")
            album_id = self.get_album_id(album)
            logger.info(f"Getting assets from album id {album_id}")
            assets = self.get_assets(album_id)

            if not assets:
                logger.error(f"No assets found in album '{album}'")
                return None

        except Exception as e:
            logger.error(f"Error retrieving album data from {self.base_url}: {e}")
            return None

        # Select random asset
        selected_asset = choice(assets)
        asset_id = selected_asset["id"]
        asset_url = f"{self.base_url}/api/assets/{asset_id}/original"

        logger.info(f"Selected random asset: {asset_id}")
        logger.debug(f"Downloading from: {asset_url}")

        # Use adaptive image loader for memory-efficient processing
        # Let loader resize when requested (when no padding will be applied)
        with self._pin():
            img = self.image_loader.from_url(
                asset_url,
                dimensions,
                timeout_ms=40000,
                resize=resize,
                headers=self.headers,
            )

        if not img:
            logger.error(f"Failed to load image {asset_id} from Immich")
            return None

        logger.info(f"Successfully loaded image: {img.size[0]}x{img.size[1]}")
        return img


class ImageAlbum(BasePlugin):
    def build_settings_schema(self):
        return schema(
            section(
                "Source",
                row(
                    field(
                        "albumProvider",
                        "select",
                        label="Album Provider",
                        default="Immich",
                        options=[option("Immich", "Immich")],
                    ),
                    field(
                        "url",
                        label="Base URL",
                        placeholder="https://immich.example.com",
                        required=True,
                    ),
                ),
                field(
                    "album",
                    label="Album Name",
                    placeholder="Family Photos",
                    required=True,
                ),
            ),
            section(
                "Display",
                row(
                    field(
                        "padImage",
                        "checkbox",
                        label="Scale to Fit",
                        hint="Keep the full image visible and pad the background instead of cropping to fill the screen.",
                        checked_value="false",
                        unchecked_value="true",
                        submit_unchecked=True,
                    ),
                    field(
                        "randomize",
                        "checkbox",
                        label="Random Order",
                        hint="Preserve random image selection when supported by the source provider.",
                        checked_value="true",
                        unchecked_value="false",
                        submit_unchecked=True,
                    ),
                ),
                row(
                    field(
                        "backgroundOption",
                        "radio_segment",
                        label="Background Fill",
                        default="blur",
                        options=[
                            option("blur", "Blur"),
                            option("color", "Color"),
                        ],
                    ),
                    field(
                        "backgroundColor",
                        "color",
                        label="Background Color",
                        default="#ffffff",
                        visible_if={"field": "backgroundOption", "equals": "color"},
                    ),
                ),
            ),
        )

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "Immich",
            "expected_key": "IMMICH_KEY",
        }
        return template_params

    def _fetch_immich_image(self, settings, device_config, dimensions, use_padding):
        """Validate Immich settings and fetch an image from the provider."""
        key = device_config.load_env_key("IMMICH_KEY")
        if not key:
            logger.error("Immich API Key not configured")
            raise RuntimeError("Immich API Key not configured.")

        url = settings.get("url")
        if not url:
            logger.error("Immich URL not provided")
            raise RuntimeError("Immich URL is required.")

        try:
            _validated_url, pinned_ips = validate_url_with_ips(url)
        except ValueError as e:
            # Permanent: bad scheme, SSRF-blocked address, or malformed URL.
            # Tell refresh_task not to retry — the URL will fail identically
            # on every subsequent attempt (JTN-778).
            raise PermanentPluginError(f"Invalid URL: {e}") from e

        album = settings.get("album")
        if not album:
            logger.error("Album name not provided")
            raise RuntimeError("Album name is required.")

        logger.info(f"Immich URL: {url}")
        logger.info(f"Album: {album}")

        provider = ImmichProvider(url, key, self.image_loader, pinned_ips=pinned_ips)
        img = provider.get_image(album, dimensions, resize=not use_padding)

        if not img:
            logger.error("Failed to retrieve image from Immich")
            raise RuntimeError("Failed to load image, please check logs.")
        return img

    def generate_image(self, settings, device_config):
        logger.info("=== Image Album Plugin: Starting image generation ===")

        dimensions = self.get_oriented_dimensions(device_config)

        img = None
        album_provider = settings.get("albumProvider")
        logger.info(f"Album provider: {album_provider}")

        # Check padding options to determine resize strategy
        use_padding = settings.get("padImage") == "true"
        background_option = settings.get("backgroundOption", "blur")
        logger.debug(
            f"Settings: pad_image={use_padding}, background_option={background_option}"
        )

        match album_provider:
            case "Immich":
                img = self._fetch_immich_image(
                    settings, device_config, dimensions, use_padding
                )
            case _:
                logger.error(f"Unknown album provider: {album_provider}")
                raise RuntimeError(f"Unsupported album provider: {album_provider}")

        if img is None:
            logger.error("Image is None after provider processing")
            raise RuntimeError("Failed to load image, please check logs.")

        # Apply padding if requested (image was loaded at full size)
        if use_padding:
            logger.debug(f"Applying padding with {background_option} background")
            if background_option == "blur":
                img = pad_image_blur(img, dimensions)
            else:
                background_color = ImageColor.getcolor(
                    settings.get("backgroundColor") or "white", img.mode
                )
                img = ImageOps.pad(
                    img,
                    dimensions,
                    color=background_color,
                    method=Image.Resampling.LANCZOS,
                )
        # else: loader already resized to fit with proper aspect ratio

        logger.info("=== Image Album Plugin: Image generation complete ===")
        return img

import logging
from collections.abc import Mapping
from typing import Any, cast

from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import (
    field,
    option,
    row,
    schema,
    section,
    widget,
)

from .github_contributions import contributions_generate_image
from .github_sponsors import sponsors_generate_image
from .github_stars import stars_generate_image

logger = logging.getLogger(__name__)


class GitHub(BasePlugin):  # type: ignore[misc, unused-ignore]
    def build_settings_schema(self) -> dict[str, object]:
        return cast(  # type: ignore[redundant-cast, unused-ignore]
            dict[str, object],
            schema(
                section(
                    "Source",
                    row(
                        field(
                            "githubType",
                            "select",
                            label="Metric",
                            default="contributions",
                            options=[
                                option("contributions", "Contributions"),
                                option("sponsors", "Sponsors"),
                                option("stars", "Stars"),
                            ],
                        ),
                        field(
                            "githubUsername",
                            label="GitHub Username",
                            placeholder="octocat",
                            required=True,
                        ),
                        field(
                            "githubRepository",
                            label="Repository",
                            placeholder="repository-name",
                            wrapper_id="repositoryGroup",
                            visible_if={"field": "githubType", "equals": "stars"},
                        ),
                    ),
                ),
                section(
                    "Contribution Grid Colors",
                    widget(
                        "github-colors",
                        template="widgets/github_colors.html",
                        visible_if={"field": "githubType", "equals": "contributions"},
                    ),
                ),
            ),
        )

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "GitHub",
            "expected_key": "GITHUB_SECRET",
        }
        template_params["style_settings"] = True
        return cast(dict[str, object], template_params)  # type: ignore[redundant-cast, unused-ignore]

    def generate_image(
        self, settings: Mapping[str, object], device_config: DeviceConfigLike
    ) -> Image.Image:
        try:
            github_type = settings.get("githubType", "contributions")

            if github_type == "contributions":
                return cast(Any, contributions_generate_image)(
                    self, settings, device_config
                )
            if github_type == "sponsors":
                return cast(Any, sponsors_generate_image)(self, settings, device_config)
            if github_type == "stars":
                return cast(Any, stars_generate_image)(self, settings, device_config)
            logger.error(f"Unknown GitHub type: {github_type}")
            raise ValueError(f"Unknown GitHub type: {github_type}")
        except Exception as e:
            logger.error(f"GitHub image generation failed: {str(e)}")
            raise

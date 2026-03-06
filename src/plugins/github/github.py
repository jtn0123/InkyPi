from ..base_plugin.base_plugin import BasePlugin
from ..base_plugin.settings_schema import field, option, row, schema, section, widget
from .github_contributions import contributions_generate_image
from .github_sponsors import sponsors_generate_image
from .github_stars import stars_generate_image
import logging

logger = logging.getLogger(__name__)


class GitHub(BasePlugin):
    def build_settings_schema(self):
        return schema(
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
                        placeholder="owner/repo",
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
        )

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "GitHub",
            "expected_key": "GITHUB_SECRET"
        }
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        try:
            github_type = settings.get('githubType', 'contributions')

            if github_type == 'contributions':
                return contributions_generate_image(self, settings, device_config)
            elif github_type == 'sponsors':
                return sponsors_generate_image(self, settings, device_config)
            elif github_type == 'stars':
                return stars_generate_image(self, settings, device_config)
            else:
                logger.error(f"Unknown GitHub type: {github_type}")
                raise ValueError(f"Unknown GitHub type: {github_type}")
        except Exception as e:
            logger.error(f"GitHub image generation failed: {str(e)}")
            raise

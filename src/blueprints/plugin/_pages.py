"""Plugin settings page, plugin index page and page-side helpers.

Includes the AI Image prompt-suggestion endpoint the settings page calls and
the API-key presence resolution used to render the settings template.
"""

from typing import Any

from flask import abort, current_app, render_template, request

from plugins.plugin_registry import get_plugin_instance
from utils.backend_errors import (
    ClientInputError,
    ResourceLookupError,
    route_error_boundary,
)
from utils.form_utils import sanitize_log_field
from utils.http_utils import json_error, json_success

from ._common import _CONFIG_KEY, _ERR_PLUGIN_INSTANCE_NOT_FOUND, logger, plugin_bp
from ._images import _find_latest_plugin_refresh_time


def _resolve_multi_service_api_key(
    api_key_meta: dict[str, Any], device_config: Any
) -> None:
    """Populate per-service presence + a display label for plugins that list
    multiple providers under ``services``. Mutates *api_key_meta* in place.

    Each entry of ``services`` is ``{name, env_var}``; this adds ``present``
    to each, sets the aggregate ``present`` flag, and picks a ``service``
    label that reflects which provider(s) are actually configured (so the
    chip shows "OpenAI" when only OpenAI is set, not "OpenAI / Google").
    """
    services = api_key_meta.get("services") or []
    resolved = []
    any_present = False
    for svc in services:
        env_var = svc.get("env_var")
        name = svc.get("name") or env_var or ""
        present = bool(env_var) and (device_config.load_env_key(env_var) is not None)
        resolved.append({"name": name, "env_var": env_var, "present": present})
        any_present = any_present or present
    api_key_meta["services"] = resolved
    api_key_meta["present"] = any_present

    configured_names = [s["name"] for s in resolved if s["present"]]
    if configured_names:
        api_key_meta["service"] = " · ".join(configured_names)
    else:
        all_names = [s["name"] for s in resolved]
        api_key_meta["service"] = " or ".join(all_names) or api_key_meta.get(
            "service", ""
        )


def _resolve_api_key_presence(
    template_params: dict[str, Any], device_config: Any
) -> None:
    """Attach ``present`` and provider-aware display metadata to ``api_key``.

    Single-provider plugins still use ``expected_key``; multi-provider plugins
    supply a ``services`` list that drives per-provider presence flags.
    """
    api_key_meta = template_params.get("api_key")
    if not api_key_meta or not api_key_meta.get("required"):
        return
    if api_key_meta.get("services"):
        _resolve_multi_service_api_key(api_key_meta, device_config)
        return
    expected_key = api_key_meta.get("expected_key")
    if expected_key:
        api_key_meta["present"] = device_config.load_env_key(expected_key) is not None


@plugin_bp.route("/plugin/<plugin_id>", methods=["GET"])
def plugin_page(plugin_id: str) -> Any:
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    plugin_config = device_config.get_plugin(plugin_id)
    if not plugin_config:
        abort(404)

    with route_error_boundary(
        "render plugin page",
        logger=logger,
        hint="Check plugin configuration and template generation.",
    ):
        plugin = get_plugin_instance(plugin_config)
        template_params = plugin.generate_settings_template()

        _resolve_api_key_presence(template_params, device_config)

        # If viewing an existing instance, pre-populate its settings
        plugin_instance_name = request.args.get("instance")
        if plugin_instance_name:
            plugin_instance = playlist_manager.find_plugin(
                plugin_id, plugin_instance_name
            )
            if not plugin_instance:
                logger.warning(
                    "Plugin instance lookup failed: plugin_id=%s instance=%s",
                    sanitize_log_field(plugin_id),
                    sanitize_log_field(plugin_instance_name),
                )
                raise ResourceLookupError(
                    _ERR_PLUGIN_INSTANCE_NOT_FOUND,
                    status=404,
                )
            template_params["plugin_settings"] = plugin_instance.settings
            template_params["plugin_instance"] = plugin_instance_name
            # "Last generated" on an instance page should be this instance's
            # own refresh, not the newest render of any instance of the plugin.
            if plugin_instance.latest_refresh_time:
                template_params["plugin_instance_last_refresh"] = (
                    plugin_instance.latest_refresh_time
                )
        else:
            # Try to pre-populate from a saved settings instance on Default playlist
            default_playlist = playlist_manager.get_playlist("Default")
            if default_playlist:
                saved_instance_name = f"{plugin_id}_saved_settings"
                saved_instance = default_playlist.find_plugin(
                    plugin_id, saved_instance_name
                )
                if saved_instance:
                    template_params["plugin_settings"] = saved_instance.settings
                    template_params["plugin_instance"] = saved_instance_name

        template_params["playlists"] = playlist_manager.get_playlist_names()

        # Find latest refresh time for this plugin (any instance)
        plugin_latest_refresh = _find_latest_plugin_refresh_time(
            device_config, plugin_id
        )
        if plugin_latest_refresh:
            template_params["plugin_latest_refresh"] = plugin_latest_refresh

    return render_template(
        "plugin.html",
        plugin=plugin_config,
        resolution=device_config.get_resolution(),
        config=device_config.get_config(),
        active_nav="plugins",
        **template_params,
    )


@plugin_bp.route("/plugin/ai_image/random_prompt", methods=["POST"])
def ai_image_random_prompt() -> Any:
    """Generate a prompt suggestion for the AI Image plugin."""
    device_config = current_app.config[_CONFIG_KEY]
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return json_error("Invalid JSON payload", status=400)

    provider = str(data.get("provider") or "openai").strip().lower()
    if provider not in ("openai", "google"):
        raise ClientInputError(
            f"Unsupported provider: {provider!r}",
            status=400,
            code="validation_error",
            field="provider",
        )
    seed_prompt = str(data.get("prompt") or "")

    with route_error_boundary(
        "generate AI image prompt",
        logger=logger,
        hint="Ensure the selected provider API key is configured.",
    ):
        if provider == "google":
            api_key = device_config.load_env_key("GOOGLE_AI_SECRET")
            if not api_key:
                raise ClientInputError("Google AI API Key not configured.", status=400)
            from google import genai

            from plugins.ai_image.ai_image import AIImage

            # Named per provider: the two branches bind unrelated SDK client
            # types, and sharing one name made the second look like a
            # reassignment to an incompatible type.
            google_client = genai.Client(api_key=api_key)
            prompt = AIImage.fetch_image_prompt_google(google_client, seed_prompt)
        else:
            api_key = device_config.load_env_key("OPEN_AI_SECRET")
            if not api_key:
                raise ClientInputError("OpenAI API Key not configured.", status=400)
            from openai import OpenAI

            from plugins.ai_image.ai_image import AIImage

            openai_client = OpenAI(api_key=api_key)
            prompt = AIImage.fetch_image_prompt(openai_client, seed_prompt)

        if not prompt:
            raise ClientInputError(
                "Prompt generator returned an empty prompt.", status=502
            )
        return json_success("Generated prompt.", prompt=prompt)


@plugin_bp.route("/plugins", methods=["GET"])
def plugins_page() -> Any:
    device_config = current_app.config[_CONFIG_KEY]
    plugins = device_config.get_plugins()

    return render_template(
        "plugins.html",
        plugins=plugins,
        config=device_config.get_config(),
        active_nav="plugins",
    )

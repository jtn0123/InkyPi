"""Subprocess worker helpers for plugin execution."""

import io
import logging
import multiprocessing
import sys
import traceback

from plugins.plugin_registry import get_plugin_instance

logger = logging.getLogger(__name__)


def _get_mp_context():
    # forkserver spawns children from a lean server process, reducing memory
    # on constrained devices like Pi Zero 2W. It requires picklable arguments,
    # so we only prefer it on Linux where the production target runs.
    prefer = ("forkserver", "fork") if sys.platform == "linux" else ("fork",)
    for method in prefer:
        try:
            return multiprocessing.get_context(method)
        except ValueError:
            continue
    return multiprocessing.get_context()


def _restore_child_config(device_config):
    from config import Config

    Config.config_file = device_config.config_file
    Config.current_image_file = device_config.current_image_file
    Config.processed_image_file = device_config.processed_image_file
    Config.plugin_image_dir = device_config.plugin_image_dir
    Config.history_image_dir = device_config.history_image_dir
    return Config()


def _remote_exception(error_type: str, error_message: str) -> BaseException:
    exc_types = {
        "RuntimeError": RuntimeError,
        "ValueError": ValueError,
        "TimeoutError": TimeoutError,
        "KeyError": KeyError,
        "TypeError": TypeError,
        "FileNotFoundError": FileNotFoundError,
    }
    exc_cls = exc_types.get(error_type, RuntimeError)
    return exc_cls(error_message)


def _execute_refresh_attempt_worker(
    result_queue,
    plugin_config: dict,
    refresh_action,
    device_config,
    current_dt,
):
    try:
        child_config = _restore_child_config(device_config)
        plugin = get_plugin_instance(plugin_config)
        image = refresh_action.execute(plugin, child_config, current_dt)
        plugin_meta = None
        if hasattr(plugin, "get_latest_metadata"):
            plugin_meta = plugin.get_latest_metadata()
        if image is None:
            raise RuntimeError("Plugin returned None image")
        image_bytes = io.BytesIO()
        image.save(image_bytes, format="PNG")
        result_queue.put(
            {
                "ok": True,
                "image_bytes": image_bytes.getvalue(),
                "plugin_meta": plugin_meta,
            }
        )
    except Exception as exc:
        result_queue.put(
            {
                "ok": False,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
            }
        )

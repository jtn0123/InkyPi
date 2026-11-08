"""``/update_now`` manual render (sync and job-queue async) and its job poller."""

from collections.abc import Mapping
from typing import Any, cast

from flask import current_app, jsonify, request

from plugins.plugin_registry import get_plugin_instance
from refresh_task import ManualRefresh
from refresh_task.job_queue import get_job_queue
from services.direct_render import (
    DirectRenderFailure,
    DirectRenderOutcome,
    execute_direct_render,
)
from utils.backend_errors import ClientInputError, RefreshTaskUnavailable
from utils.fallback_image import render_error_image
from utils.form_utils import sanitize_log_field
from utils.http_utils import json_error, json_success
from utils.plugin_errors import (
    MANUAL_UPDATE_TIMEOUT_MSG,
    SCREENSHOT_BACKEND_UNAVAILABLE_MSG,
    ProviderReportedPluginError,
    ScreenshotBackendError,
)
from utils.request_models import RequestModelError, parse_plugin_update_now_request
from utils.security_utils import URLValidationError

from ._common import (
    _CONFIG_KEY,
    _ERR_INTERNAL,
    _ERR_PLUGIN_NOT_FOUND,
    _MSG_DISPLAY_UPDATED,
    _plugin_form_data,
    _raise_request_model_error,
    logger,
    plugin_bp,
)


def _safe_display_image(
    display_manager: Any,
    image: Any,
    image_settings: Any,
    history_meta: Mapping[str, Any] | None,
) -> Any:
    """Invoke display_manager.display_image, tolerating older stubs without ``history_meta``.

    Some test doubles monkeypatch ``display_image`` with a (image, image_settings)
    signature.  We prefer to pass ``history_meta`` so the history sidecar records
    the plugin_id — without it, /plugin_latest_image/<plugin_id> cannot find the
    image and the "Latest from this plugin" card stays empty (JTN-341).
    """
    try:
        return display_manager.display_image(
            image, image_settings=image_settings, history_meta=history_meta
        )
    except TypeError:
        # Legacy/test stub without the history_meta kwarg
        return display_manager.display_image(image, image_settings=image_settings)


def _direct_render_outcome(
    plugin_id: str,
    plugin_settings: dict[str, Any],
    device_config: Any,
    display_manager: Any,
) -> DirectRenderOutcome:
    plugin_config = device_config.get_plugin(plugin_id)
    if not plugin_config:
        return DirectRenderOutcome(False, _ERR_PLUGIN_NOT_FOUND, 404, "not_found")
    history_meta = {
        "refresh_type": "Manual Update",
        "plugin_id": plugin_id,
        "playlist": None,
        "plugin_instance": None,
    }

    def display(image: Any) -> None:
        _safe_display_image(
            display_manager,
            image,
            plugin_config.get("image_settings", []),
            history_meta,
        )

    def timings() -> tuple[int | None, int | None]:
        info = device_config.get_refresh_info()
        return getattr(info, "display_ms", None), getattr(info, "preprocess_ms", None)

    def fallback(error: BaseException, record_history: bool) -> None:
        message = (
            "Unexpected error generating preview for %s"
            if not isinstance(error, RuntimeError)
            else "Plugin failed during direct render for %s"
        )
        logger.error(message, sanitize_log_field(plugin_id), exc_info=error)
        _push_update_now_fallback(
            plugin_id,
            plugin_config,
            device_config,
            display_manager,
            error,
            record_history=record_history,
        )

    return execute_direct_render(
        lambda: get_plugin_instance(plugin_config).generate_image(
            plugin_settings, device_config
        ),
        display,
        timings,
        fallback,
    )


def _update_now_direct(
    plugin_id: str,
    plugin_settings: dict[str, Any],
    device_config: Any,
    display_manager: Any,
) -> Any:
    outcome = _direct_render_outcome(
        plugin_id, plugin_settings, device_config, display_manager
    )
    if outcome.ok:
        return json_success(message=outcome.message, metrics=outcome.metrics)
    return json_error(
        outcome.message,
        status=outcome.status,
        code=outcome.code,
        details=outcome.details or None,
    )


def _push_update_now_fallback(
    plugin_id: str,
    plugin_config: dict[str, Any] | Mapping[str, Any],
    device_config: Any,
    display_manager: Any,
    exc: BaseException,
    *,
    record_history: bool = True,
) -> None:
    """Best-effort: render and push an error-card image so the display updates on failure.

    ``record_history``: when False, the fallback is *displayed* but no
    history sidecar is written, so the failure does not get counted by
    :mod:`utils.refresh_stats` toward the dashboard "Refreshes / Errors"
    KPIs. Use False for failures that are pre-render input rejections
    (e.g. URLValidationError) — those didn't actually attempt a real
    render, and counting them inflates both the refresh and error
    counters for what was just a typo (ISSUE-006).
    """
    try:
        w, h = device_config.get_resolution()
        fallback = render_error_image(
            width=w,
            height=h,
            plugin_id=plugin_id,
            instance_name=None,
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        history_meta = (
            {
                "refresh_type": "Manual Update",
                "plugin_id": plugin_id,
                "playlist": None,
                "plugin_instance": None,
                "error_class": type(exc).__name__,
            }
            if record_history
            else None
        )
        _safe_display_image(
            display_manager,
            fallback,
            plugin_config.get("image_settings", []),
            history_meta,
        )
    except Exception:
        logger.warning(
            "update_now: fallback display failed for %s",
            sanitize_log_field(plugin_id),
            exc_info=True,
        )


@plugin_bp.route("/api/job/<job_id>", methods=["GET"])
def job_status(job_id: str) -> tuple[Any, int]:
    """Poll the status of an asynchronous render job."""
    queue = get_job_queue()
    info = queue.get_status(job_id)
    return jsonify(info), 200


def _run_update_now(
    app: Any, plugin_id: str, plugin_settings: dict[str, Any]
) -> dict[str, Any]:
    """Execute plugin render in a background thread (job-queue worker).

    Needs the Flask *app* so we can push an application context — the worker
    thread has none by default.
    """
    with app.app_context():
        device_config = app.config[_CONFIG_KEY]
        refresh_task = app.config["REFRESH_TASK"]
        display_manager = app.config["DISPLAY_MANAGER"]

        if refresh_task.running:
            metrics = refresh_task.manual_update(
                ManualRefresh(plugin_id, plugin_settings)
            )
            return {
                "success": True,
                "message": _MSG_DISPLAY_UPDATED,
                "metrics": metrics,
            }

        outcome = _direct_render_outcome(
            plugin_id, plugin_settings, device_config, display_manager
        )
        if not outcome.ok:
            raise DirectRenderFailure(outcome)
        return {"success": True, "message": outcome.message, "metrics": outcome.metrics}


@plugin_bp.route("/update_now", methods=["POST"])
def update_now() -> Any:
    """Render a plugin image and push it to the display.

    When the client sends ``X-Async: true`` (or ``?async=1``), the render is
    enqueued on a background thread and the response is **202 Accepted** with
    ``{"job_id": "…"}``.  The caller then polls ``GET /api/job/<job_id>``
    until status is ``done`` or ``error``.

    Without the async flag the request behaves synchronously (legacy mode) so
    existing callers and tests are unaffected.
    """
    device_config = current_app.config[_CONFIG_KEY]
    refresh_task = current_app.config["REFRESH_TASK"]
    display_manager = current_app.config["DISPLAY_MANAGER"]

    plugin_id: str | None = None
    try:
        parsed, parse_error = parse_plugin_update_now_request(
            _plugin_form_data(),
            async_header=request.headers.get("X-Async", ""),
            async_query=request.args.get("async", ""),
        )
        if parse_error is not None:
            _raise_request_model_error(parse_error)
        if parsed is None:
            _raise_request_model_error(
                RequestModelError(message="Invalid form payload", status=400)
            )
        plugin_id = parsed.plugin_id
        plugin_settings = parsed.plugin_settings

        if parsed.want_async:
            queue = get_job_queue()
            # `current_app` is a LocalProxy at runtime, but flask types it as
            # `Flask` for convenience, so the unwrap is invisible to mypy. The
            # real object is needed because the proxy is bound to this request
            # context and the job runs outside it.
            app = cast(Any, current_app)._get_current_object()
            job_id = queue.enqueue(_run_update_now, app, plugin_id, plugin_settings)
            return jsonify({"job_id": job_id}), 202

        # --- Synchronous (legacy) path ---
        if refresh_task.running:
            metrics = refresh_task.manual_update(
                ManualRefresh(plugin_id, plugin_settings)
            )
            return json_success(message=_MSG_DISPLAY_UPDATED, metrics=metrics)
        logger.info("Refresh task not running, updating display directly")
        return _update_now_direct(
            plugin_id, plugin_settings, device_config, display_manager
        )
    except URLValidationError as e:
        # JTN-776: URL validation failures surfaced through the refresh-task
        # path (manual_update re-raises the plugin's exception) must become
        # HTTP 4xx, not 500, so the user sees the real reason. ``safe_message``
        # returns a whitelisted string from :mod:`utils.security_utils`, so no
        # exception-derived text reaches the response body (CodeQL
        # ``py/stack-trace-exposure``).
        safe_msg = e.safe_message()
        logger.info(
            "update_now: URL validation rejected plugin %s: %s",
            sanitize_log_field(plugin_id or "?"),
            sanitize_log_field(safe_msg),
        )
        return json_error(
            safe_msg,
            status=422,
            code="validation_error",
            details={"field": "url"},
        )
    except ScreenshotBackendError:
        # JTN-789: chromium subprocess failed twice in a row (initial + one
        # retry). Surface a specific 503 ``backend_unavailable`` with a
        # whitelisted constant message so CodeQL ``py/stack-trace-exposure``
        # cannot taint-track exception text into the HTTP body (mirrors the
        # JTN-776 URLValidationError pattern). exc_info is intentionally
        # NOT captured — plugin_id is enough for operators to correlate
        # with the upstream chromium error ``take_screenshot`` already logged.
        logger.warning(
            "update_now: screenshot backend unavailable for plugin %s",
            sanitize_log_field(plugin_id or "?"),
        )
        return json_error(
            SCREENSHOT_BACKEND_UNAVAILABLE_MSG,
            status=503,
            code="backend_unavailable",
        )
    except TimeoutError:
        # JTN-K4: covers the alternate path where ``refresh_task.running``
        # is True and ``manual_update`` re-raises TimeoutError from the
        # subprocess worker (preserved via ``_remote_exception`` since the
        # exception was added to the allow-list alongside JTN-789).
        # Without this handler the exception falls through to the generic
        # 500 ``internal_error`` below.  Message comes from a module
        # constant so CodeQL ``py/stack-trace-exposure`` cannot taint
        # exception text into the body.
        logger.warning(
            "update_now: manual update timed out for plugin %s",
            sanitize_log_field(plugin_id or "?"),
        )
        return json_error(
            MANUAL_UPDATE_TIMEOUT_MSG,
            status=504,
            code="manual_update_timeout",
        )
    except ProviderReportedPluginError as e:
        safe_msg = e.safe_message()
        logger.info(
            "update_now: provider rejected plugin %s: %s",
            sanitize_log_field(plugin_id or "?"),
            sanitize_log_field(str(e)),
        )
        return json_error(
            safe_msg,
            status=400,
            code="provider_rejected",
        )
    except (ClientInputError, RefreshTaskUnavailable) as e:
        return json_error(
            e.message,
            status=e.status,
            code=e.code,
            details=e.details,
        )
    except Exception as e:
        logger.exception("Error in update_now: %s", e)
        return json_error(_ERR_INTERNAL, status=500, code="internal_error")

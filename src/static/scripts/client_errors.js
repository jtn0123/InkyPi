// Report uncaught JS errors and unhandled promise rejections to the server.
// Relies on the /settings/client_log endpoint already present in settings.py.
(function () {
  "use strict";
  const ENDPOINT = "/settings/client_log";
  const THROTTLE_MS = 5000; // at most one report per 5 seconds
  let lastReport = 0;

  function getRejectionMessage(reason) {
    if (reason instanceof Error) {
      return reason.message;
    }
    if (typeof reason === "string") {
      return reason;
    }
    return "Unhandled promise rejection";
  }

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function report(message, extra) {
    const now = Date.now();
    if (now - lastReport < THROTTLE_MS) return;
    lastReport = now;
    try {
      const csrfToken = getCsrfToken();
      const body = JSON.stringify({
        level: "error",
        message,
        extra,
        _csrf_token: csrfToken,
      });
      // Use navigator.sendBeacon if available (works during page unload).
      // CSRF token is embedded in the JSON body because sendBeacon does not
      // support custom request headers.
      if (navigator.sendBeacon) {
        navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" }));
      } else {
        fetch(ENDPOINT, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: body,
        }).catch(function () {});
      }
    } catch (e) {
      // Swallow — never let error reporting itself throw
    }
  }

  window.addEventListener("error", function (event) {
    report("Uncaught error: " + (event.message || "unknown"), {
      filename: event.filename || "",
      lineno: event.lineno || 0,
      colno: event.colno || 0,
      url: location.pathname,
    });
  });

  window.addEventListener("unhandledrejection", function (event) {
    const reason = event.reason;
    const message = getRejectionMessage(reason);
    report(message, {
      stack: reason instanceof Error ? (reason.stack || "").slice(0, 500) : "",
      url: location.pathname,
    });
  });
})();

// Report uncaught JS errors and unhandled promise rejections to the server.
// Relies on the /settings/client_log endpoint already present in settings.py.
(function () {
  "use strict";
  var ENDPOINT = "/settings/client_log";
  var _lastReport = 0;
  var THROTTLE_MS = 5000; // at most one report per 5 seconds

  function report(message, extra) {
    var now = Date.now();
    if (now - _lastReport < THROTTLE_MS) return;
    _lastReport = now;
    try {
      var body = JSON.stringify({
        level: "error",
        message: message,
        extra: extra,
      });
      // Use navigator.sendBeacon if available (works during page unload)
      if (navigator.sendBeacon) {
        navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" }));
      } else {
        fetch(ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
    var reason = event.reason;
    var message =
      reason instanceof Error
        ? reason.message
        : typeof reason === "string"
        ? reason
        : "Unhandled promise rejection";
    report(message, {
      stack: reason instanceof Error ? (reason.stack || "").slice(0, 500) : "",
      url: location.pathname,
    });
  });
})();

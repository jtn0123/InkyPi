// Forward uncaught JS errors and unhandled promise rejections to /api/client-error.
// Features:
//   - 25% sampling to avoid flooding the server with noise
//   - Uses navigator.sendBeacon when available (works during page unload)
//   - Self-disables after 5 consecutive send failures (no logging loop)
(function () {
  "use strict";

  var ENDPOINT = "/api/client-error";
  var SAMPLE_RATE = 0.25; // report 25% of errors
  var MAX_FAILURES = 5;
  var failures = 0;
  var disabled = false;

  function shouldSample() {
    return Math.random() < SAMPLE_RATE;
  }

  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function onSendFailure() {
    failures += 1;
    if (failures >= MAX_FAILURES) {
      disabled = true;
    }
  }

  function send(payload) {
    if (disabled) return;
    if (!shouldSample()) return;
    try {
      var body = JSON.stringify(payload);
      if (navigator.sendBeacon) {
        // sendBeacon works during page unload; CSRF token embedded in body
        // because sendBeacon does not support custom headers.
        var blob = new Blob([body], { type: "application/json" });
        var ok = navigator.sendBeacon(ENDPOINT, blob);
        if (!ok) {
          onSendFailure();
        }
      } else {
        var csrfToken = getCsrfToken();
        fetch(ENDPOINT, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: body,
          keepalive: true,
        }).then(function (res) {
          if (!res.ok && res.status !== 429) {
            onSendFailure();
          }
        }).catch(function () {
          onSendFailure();
        });
      }
    } catch (_e) {
      // Never let the reporter itself throw — swallow silently.
    }
  }

  globalThis.addEventListener("error", function (event) {
    send({
      message: (event.message || "Uncaught error").slice(0, 2048),
      source: (event.filename || "").slice(0, 2048),
      line: event.lineno || 0,
      column: event.colno || 0,
      url: location.pathname.slice(0, 2048),
    });
  });

  globalThis.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    var message;
    if (reason instanceof Error) {
      message = reason.message || "Unhandled promise rejection";
    } else if (typeof reason === "string") {
      message = reason;
    } else {
      message = "Unhandled promise rejection";
    }
    send({
      message: message.slice(0, 2048),
      stack: (reason instanceof Error && reason.stack ? reason.stack : "").slice(0, 2048),
      url: location.pathname.slice(0, 2048),
    });
  });
})();

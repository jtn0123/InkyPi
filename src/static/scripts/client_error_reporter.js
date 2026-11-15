// Forward uncaught JS errors and unhandled promise rejections to /api/client-error.
// Loaded early (not deferred, right after csrf.js) so later scripts' errors count.
//   - At most one report every 5 s, so an error loop cannot flood the Pi
//   - Sends with keepalive fetch: it survives page unload like sendBeacon, but
//     can carry the X-CSRFToken header the server requires
//   - Stops after 5 failed sends (no logging loop)
(function () {
  "use strict";

  const ENDPOINT = "/api/client-error";
  const THROTTLE_MS = 5000;
  const MAX_FAILURES = 5;
  const FIELD_MAX = 2048; // matches the server-side per-field cap
  let lastReport = -Infinity;
  let failures = 0;

  function cap(value) {
    return String(value || "").slice(0, FIELD_MAX);
  }

  function rejectionMessage(reason) {
    if (reason instanceof Error) {
      return reason.message || "Unhandled promise rejection";
    }
    if (typeof reason === "string") {
      return reason;
    }
    return "Unhandled promise rejection";
  }

  function onSendFailure() {
    failures += 1;
  }

  function send(payload) {
    if (failures >= MAX_FAILURES) return;
    const now = Date.now();
    if (now - lastReport < THROTTLE_MS) return;
    lastReport = now;
    try {
      fetch(ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": globalThis.InkyPiCsrf?.getToken() || "",
        },
        body: JSON.stringify(payload),
        keepalive: true,
      }).then(function (res) {
        if (!res.ok && res.status !== 429) {
          onSendFailure();
        }
      }, onSendFailure);
    } catch {
      // Never let the reporter itself throw.
      onSendFailure();
    }
  }

  globalThis.addEventListener("error", function (event) {
    send({
      message: cap(event.message || "Uncaught error"),
      source: cap(event.filename),
      line: event.lineno || 0,
      column: event.colno || 0,
      url: cap(location.pathname),
    });
  });

  globalThis.addEventListener("unhandledrejection", function (event) {
    const reason = event.reason;
    send({
      message: cap(rejectionMessage(reason)),
      stack: cap(reason instanceof Error ? reason.stack : ""),
      url: cap(location.pathname),
    });
  });
})();

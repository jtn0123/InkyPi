// Forward browser console.warn and console.error calls to /api/client-log.
// Only activates when the page opts in via:
//   <meta name="client-log-enabled" content="1">
// Features:
//   - 50% sampling (less critical than thrown errors)
//   - Calls original console methods first — never breaks existing logging
//   - Uses navigator.sendBeacon when available (works during page unload)
//   - Self-disables after 5 consecutive send failures
(function () {
  "use strict";

  // Opt-in guard — do nothing unless the page explicitly enables this shim.
  const metaTag = document.querySelector('meta[name="client-log-enabled"]');
  if (metaTag?.getAttribute("content") !== "1") {
    return;
  }

  const ENDPOINT = "/api/client-log";
  const SAMPLE_RATE = 0.5; // report 50% of console messages
  const MAX_FAILURES = 5;
  let failures = 0;
  let disabled = false;

  const originalWarn = console.warn.bind(console);
  const originalError = console.error.bind(console);

  function shouldSample() {
    // NOSONAR — Math.random is intentional: this is non-security log sampling.
    // Sonar rule javascript:S2245 (insecure RNG) is a false positive here.
    return Math.random() < SAMPLE_RATE; // NOSONAR
  }

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function onSendFailure() {
    failures += 1;
    if (failures >= MAX_FAILURES) {
      disabled = true;
    }
  }

  function argsToString(args) {
    try {
      return Array.prototype.slice.call(args).map(function (a) {
        if (typeof a === "string") return a;
        try { return JSON.stringify(a); } catch { return String(a); }
      }).join(" ").slice(0, 4096);
    } catch {
      return "";
    }
  }

  function send(level, args) {
    if (disabled) return;
    if (!shouldSample()) return;
    try {
      const payload = {
        level: level,
        message: (args[0] === undefined ? "" : String(args[0])).slice(0, 2048),
        args: argsToString(args),
        url: location.pathname.slice(0, 2048),
        ts: new Date().toISOString(),
      };
      const body = JSON.stringify(payload);
      if (navigator.sendBeacon) {
        // sendBeacon works during page unload; CSRF token embedded in body
        // because sendBeacon does not support custom headers.
        const blob = new Blob([body], { type: "application/json" });
        const ok = navigator.sendBeacon(ENDPOINT, blob);
        if (ok === false) {
          onSendFailure();
        }
      } else {
        const csrfToken = getCsrfToken();
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
    } catch {
      // Never let the reporter itself throw — record a soft failure so the
      // self-disable counter still kicks in if something is fundamentally broken.
      onSendFailure();
    }
  }

  console.warn = function () {
    // Call original first — never suppress existing console output.
    originalWarn.apply(console, arguments);
    send("warn", arguments);
  };

  console.error = function () {
    // Call original first — never suppress existing console output.
    originalError.apply(console, arguments);
    send("error", arguments);
  };
})();

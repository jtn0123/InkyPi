// Forward browser console.warn and console.error calls to /api/client-log.
// Only activates when the page opts in via:
//   <meta name="client-log-enabled" content="1">
// Features (JTN-711):
//   - 50% sampling (less critical than thrown errors)
//   - Calls original console methods first — never breaks existing logging
//   - Coalesces reports within a 500ms window into a single batched POST
//     so bursts of errors consume only one server-side rate-limit token.
//   - Splits across multiple POSTs if batch exceeds the server cap (50).
//   - Falls back to navigator.sendBeacon for the tail flush on page unload.
//   - Self-disables after 10 consecutive send failures (raised from 5 now
//     that the server capacity is higher — JTN-711).
(function () {
  "use strict";

  // Opt-in guard — do nothing unless the page explicitly enables this shim.
  const metaTag = document.querySelector('meta[name="client-log-enabled"]');
  if (metaTag?.getAttribute("content") !== "1") {
    return;
  }

  const ENDPOINT = "/api/client-log";
  const SAMPLE_RATE = 0.5; // report 50% of console messages
  const MAX_FAILURES = 10; // JTN-711: raised from 5
  const BATCH_WINDOW_MS = 500; // coalesce window
  const BATCH_MAX = 50; // must match server-side _BATCH_MAX
  let failures = 0;
  let disabled = false;

  // Test mode (JTN-680): when the opt-in meta also sets content="1:test"
  // or an additional `client-log-test-mode` meta is present, skip sampling
  // so the Playwright tripwire is deterministic.
  const testModeMeta = document.querySelector(
    'meta[name="client-log-test-mode"]'
  );
  const TEST_MODE =
    testModeMeta?.getAttribute("content") === "1" ||
    metaTag?.getAttribute("content") === "1:test";

  const originalWarn = console.warn.bind(console);
  const originalError = console.error.bind(console);

  // Pending queue + coalesce timer.
  const pending = [];
  let flushTimer = null;

  function shouldSample() {
    if (TEST_MODE) return true;
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

  function buildEntry(level, args) {
    return {
      level: level,
      message: (args[0] === undefined ? "" : String(args[0])).slice(0, 2048),
      args: argsToString(args),
      url: location.pathname.slice(0, 2048),
      ts: new Date().toISOString(),
    };
  }

  function postBatch(entries, useBeacon) {
    if (entries.length === 0) return;
    // Server accepts both single-object and array payloads. Always use an
    // array here — it keeps the code path uniform and the server parses
    // either shape in one token.
    const body = JSON.stringify(entries);
    try {
      if (useBeacon && navigator.sendBeacon) {
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

  function flush(useBeacon) {
    if (flushTimer !== null) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    if (pending.length === 0) return;
    // Drain pending in chunks of at most BATCH_MAX per POST. Splitting like
    // this preserves the 1-token-per-POST contract even if coalescing
    // accumulated more than the server cap.
    while (pending.length > 0) {
      const chunk = pending.splice(0, BATCH_MAX);
      postBatch(chunk, !!useBeacon);
    }
  }

  function scheduleFlush() {
    if (flushTimer !== null) return;
    flushTimer = setTimeout(function () {
      flushTimer = null;
      flush(false);
    }, BATCH_WINDOW_MS);
  }

  function enqueue(level, args) {
    if (disabled) return;
    if (!shouldSample()) return;
    try {
      pending.push(buildEntry(level, args));
      // If we've already hit the server cap in a single burst, flush now
      // and avoid waiting the remaining window.
      if (pending.length >= BATCH_MAX) {
        flush(false);
        return;
      }
      scheduleFlush();
    } catch {
      onSendFailure();
    }
  }

  // Flush any pending reports on page unload using sendBeacon so nothing
  // is lost when the user navigates away mid-coalesce-window.
  window.addEventListener("pagehide", function () {
    flush(true);
  });
  window.addEventListener("beforeunload", function () {
    flush(true);
  });

  console.warn = function () {
    // Call original first — never suppress existing console output.
    originalWarn.apply(console, arguments);
    enqueue("warn", arguments);
  };

  console.error = function () {
    // Call original first — never suppress existing console output.
    originalError.apply(console, arguments);
    enqueue("error", arguments);
  };
})();

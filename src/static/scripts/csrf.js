// Auto-inject CSRF token into all mutating fetch requests.
// Reads the token from <meta name="csrf-token"> set in base.html.
(function () {
  "use strict";
  const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
  const originalFetch = window.fetch;

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function applyCsrfHeader(init, token) {
    // Preserve caller-provided header containers while only filling the token if absent.
    if (init.headers instanceof Headers) {
      if (!init.headers.has("X-CSRFToken")) {
        init.headers.set("X-CSRFToken", token);
      }
      return;
    }

    if (Array.isArray(init.headers)) {
      const hasToken = init.headers.some(function (pair) {
        return pair[0] === "X-CSRFToken";
      });
      if (!hasToken) {
        init.headers.push(["X-CSRFToken", token]);
      }
      return;
    }

    init.headers = init.headers ? { ...init.headers } : {};
    if (!init.headers["X-CSRFToken"]) {
      init.headers["X-CSRFToken"] = token;
    }
  }

  window.fetch = function (resource, init) {
    const requestInit = init || {};
    const method = (requestInit.method || "GET").toUpperCase();
    if (!SAFE_METHODS.has(method)) {
      const token = getCsrfToken();
      if (token) {
        applyCsrfHeader(requestInit, token);
      }
    }
    return originalFetch.call(this, resource, requestInit);
  };
})();

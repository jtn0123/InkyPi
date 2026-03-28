// Auto-inject CSRF token into all mutating fetch requests.
// Reads the token from <meta name="csrf-token"> set in base.html.
(function () {
  "use strict";
  var SAFE_METHODS = ["GET", "HEAD", "OPTIONS"];
  var originalFetch = window.fetch;

  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  window.fetch = function (resource, init) {
    init = init || {};
    var method = (init.method || "GET").toUpperCase();
    if (SAFE_METHODS.indexOf(method) === -1) {
      var token = getCsrfToken();
      if (token) {
        // Merge into existing headers without overwriting
        if (init.headers instanceof Headers) {
          if (!init.headers.has("X-CSRFToken")) {
            init.headers.set("X-CSRFToken", token);
          }
        } else if (Array.isArray(init.headers)) {
          var hasToken = init.headers.some(function (pair) {
            return pair[0] === "X-CSRFToken";
          });
          if (!hasToken) {
            init.headers.push(["X-CSRFToken", token]);
          }
        } else {
          init.headers = Object.assign({}, init.headers || {});
          if (!init.headers["X-CSRFToken"]) {
            init.headers["X-CSRFToken"] = token;
          }
        }
      }
    }
    return originalFetch.call(this, resource, init);
  };
})();

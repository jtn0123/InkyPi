// Compatibility shim for older templates. Prefer theme.js directly.
(function () {
  function boot() {
    if (window.InkyPiTheme && typeof window.InkyPiTheme.init === "function") {
      window.InkyPiTheme.init();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

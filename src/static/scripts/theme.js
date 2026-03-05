// Canonical theme bootstrap shared across all pages.
(function () {
  const STORAGE_KEYS = ["theme", "inkypi-theme"];
  const LIGHT_THEME = "light";
  const DARK_THEME = "dark";

  function getStoredTheme() {
    try {
      const legacyTheme = localStorage.getItem('theme');
      if (legacyTheme === LIGHT_THEME || legacyTheme === DARK_THEME) {
        return legacyTheme;
      }
      for (const key of STORAGE_KEYS) {
        const value = localStorage.getItem(key);
        if (value === LIGHT_THEME || value === DARK_THEME) {
          return value;
        }
      }
    } catch (e) {}
    return null;
  }

  function storeTheme(theme) {
    try {
      for (const key of STORAGE_KEYS) {
        localStorage.setItem(key, theme);
      }
    } catch (e) {}
  }

  function getPreferredTheme() {
    const stored = getStoredTheme();
    if (stored === LIGHT_THEME || stored === DARK_THEME) return stored;
    if (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    ) {
      return DARK_THEME;
    }
    return LIGHT_THEME;
  }

  function updateToggleButton(theme) {
    const button =
      document.getElementById("themeToggle") ||
      document.querySelector(".dark-mode-toggle");
    if (!button) return;
    const hoverText =
      theme === DARK_THEME ? "Toggle Light Mode" : "Toggle Dark Mode";
    button.setAttribute("data-hover-text", hoverText);
    button.setAttribute("aria-pressed", String(theme === DARK_THEME));
  }

  function applyTheme(theme) {
    const html = document.documentElement;
    html.setAttribute("data-theme", theme);
    updateToggleButton(theme);
  }

  function toggleTheme(event) {
    if (event && typeof event.preventDefault === "function") {
      event.preventDefault();
    }
    const current =
      document.documentElement.getAttribute("data-theme") || LIGHT_THEME;
    const next = current === DARK_THEME ? LIGHT_THEME : DARK_THEME;
    storeTheme(next);
    applyTheme(next);
    return next;
  }

  function init() {
    applyTheme(getPreferredTheme());
    const button =
      document.getElementById("themeToggle") ||
      document.querySelector(".dark-mode-toggle");
    if (button && !button.dataset.themeBound) {
      button.dataset.themeBound = "true";
      button.addEventListener("click", toggleTheme);
    }
    try {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      mq.addEventListener("change", function () {
        if (!getStoredTheme()) applyTheme(getPreferredTheme());
      });
    } catch (e) {}
  }

  try {
    const earlyTheme = getPreferredTheme();
    // document.documentElement.setAttribute('data-theme', earlyTheme)
    document.documentElement.setAttribute("data-theme", earlyTheme);
  } catch (e) {}

  window.InkyPiTheme = {
    applyTheme,
    getPreferredTheme,
    getStoredTheme,
    init,
    toggleTheme,
  };
  window.toggleDarkMode = toggleTheme;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

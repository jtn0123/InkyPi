(function () {
  function toggleCollapsible(button) {
    const content = button && button.nextElementSibling;
    const icon = button && button.querySelector(".collapsible-icon");
    if (!button || !content) return;
    const isOpen = !content.hidden;
    button.classList.toggle("active", !isOpen);
    button.setAttribute("aria-expanded", String(!isOpen));
    content.hidden = isOpen;
    if (icon) icon.textContent = isOpen ? "▼" : "▲";
  }

  function setCollapsibles(open, selector) {
    const buttons = document.querySelectorAll(
      selector || ".collapsible-header"
    );
    buttons.forEach((button) => {
      const content = button.nextElementSibling;
      const icon = button.querySelector(".collapsible-icon");
      button.classList.toggle("active", open);
      button.setAttribute("aria-expanded", String(open));
      if (content) content.hidden = !open;
      if (icon) icon.textContent = open ? "▲" : "▼";
    });
  }

  function jumpToSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (!section) return;
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    section.classList.add("section-focus");
    setTimeout(() => section.classList.remove("section-focus"), 1000);
  }

  function savePref(prefix, key, value) {
    try {
      localStorage.setItem(prefix + key, String(value));
    } catch (e) {}
  }

  function loadPref(prefix, key, defaultValue) {
    try {
      const value = localStorage.getItem(prefix + key);
      return value === null ? defaultValue : value;
    } catch (e) {
      return defaultValue;
    }
  }

  function setPanelLoading(id, loading) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle("loading-panel", !!loading);
    el.setAttribute("aria-busy", loading ? "true" : "false");
  }

  function debounce(fn, wait) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(null, args), wait);
    };
  }

  window.InkyPiUI = {
    debounce,
    jumpToSection,
    loadPref,
    savePref,
    setCollapsibles,
    setPanelLoading,
    toggleCollapsible,
  };
})();

(function () {
  function toggleCollapsible(button) {
    const content = button && button.nextElementSibling;
    const icon = button && button.querySelector(".collapsible-icon");
    if (!button || !content) return;
    const isOpen = content.classList.contains("is-open");
    button.classList.toggle("active", !isOpen);
    button.setAttribute("aria-expanded", String(!isOpen));
    content.classList.toggle("is-open", !isOpen);
    content.removeAttribute("hidden");
    if (icon) icon.textContent = isOpen ? "▼" : "▲";
    const sectionId = button.closest('.collapsible')?.id;
    if (sectionId) {
      savePref('collapsible_', sectionId, !isOpen);
    }
  }

  function restoreCollapsibles(selector) {
    const buttons = document.querySelectorAll(selector || ".collapsible-header");
    buttons.forEach((button) => {
      const section = button.closest('.collapsible');
      const sectionId = section?.id;
      if (!sectionId) return;
      const saved = loadPref('collapsible_', sectionId, null);
      if (saved === null) return;
      const shouldBeOpen = saved === 'true';
      const content = button.nextElementSibling;
      const icon = button.querySelector(".collapsible-icon");
      const isOpen = content && content.classList.contains("is-open");
      if (shouldBeOpen !== isOpen) {
        button.classList.toggle("active", shouldBeOpen);
        button.setAttribute("aria-expanded", String(shouldBeOpen));
        if (content) {
          content.classList.toggle("is-open", shouldBeOpen);
          content.removeAttribute("hidden");
        }
        if (icon) icon.textContent = shouldBeOpen ? "▲" : "▼";
      }
    });
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
      if (content) {
        content.classList.toggle("is-open", open);
        content.removeAttribute("hidden");
      }
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
    } catch (e) {
      // Intentionally ignored — localStorage may be unavailable (private browsing / storage full)
      console.warn("savePref: localStorage unavailable", e);
    }
  }

  function loadPref(prefix, key, defaultValue) {
    try {
      const value = localStorage.getItem(prefix + key);
      return value === null ? defaultValue : value;
    } catch (e) {
      // Intentionally ignored — localStorage may be unavailable; return the default value
      return defaultValue;
    }
  }

  function setPanelLoading(id, loading) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle("loading-panel", !!loading);
    el.setAttribute("aria-busy", loading ? "true" : "false");
  }

  function syncModalOpenState() {
    var open = document.querySelector('.modal.is-open, .thumbnail-preview-modal.is-open');
    document.body.classList.toggle('modal-open', !!open);
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
    restoreCollapsibles,
    savePref,
    setCollapsibles,
    setPanelLoading,
    syncModalOpenState,
    toggleCollapsible,
  };
})();

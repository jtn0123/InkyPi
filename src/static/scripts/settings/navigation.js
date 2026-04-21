(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function createNavigationModule({ state, ui, mobileQuery }) {
    function initializeCollapsibles() {
      if (ui.restoreCollapsibles) {
        ui.restoreCollapsibles(".collapsible-header");
      }
    }

    function initializeMobilePanelState() {
      // Only auto-expand the first collapsible when we're on mobile widths —
      // on desktop the user expects the baseline collapsed state so they can
      // choose what to open. Without this guard, tabs with collapsibles (e.g.
      // Diagnostics on the "maintenance" tab) auto-expand on tab switch,
      // which breaks the JTN-643 chevron contract on desktop.
      if (!mobileQuery?.matches) return;
      const panel = document.querySelector(
        `[data-settings-panel="${state.activeTab}"]`
      );
      if (!panel) return;
      const openSection = panel.querySelector(".collapsible-content.is-open");
      if (openSection) return;
      const firstToggle = panel.querySelector("[data-collapsible-toggle]");
      if (
        firstToggle &&
        firstToggle.getAttribute("aria-expanded") !== "true" &&
        ui.toggleCollapsible
      ) {
        ui.toggleCollapsible(firstToggle);
      }
    }

    function setActiveTab(tab) {
      state.activeTab = tab;
      for (const button of document.querySelectorAll("[data-settings-tab]")) {
        const isActive = button.dataset.settingsTab === tab;
        button.classList.toggle("active", isActive);
        if (isActive && mobileQuery.matches) {
          button.scrollIntoView({
            inline: "center",
            block: "nearest",
            behavior: "smooth",
          });
        }
      }
      for (const panel of document.querySelectorAll("[data-settings-panel]")) {
        const isActive = panel.dataset.settingsPanel === tab;
        panel.classList.toggle("active", isActive);
        panel.setAttribute("aria-hidden", isActive ? "false" : "true");
      }
      initializeMobilePanelState();
    }

    function initializeTabs() {
      for (const button of document.querySelectorAll("[data-settings-tab]")) {
        button.addEventListener("click", () =>
          setActiveTab(button.dataset.settingsTab)
        );
      }
      setActiveTab("device");
    }

    function initMobileNav() {
      const navToggle = document.getElementById("settingsMobileNavToggle");
      const sideNav = document.getElementById("settingsSideNav");
      if (navToggle && sideNav) {
        navToggle.addEventListener("click", () => {
          const isOpen = sideNav.classList.toggle("is-open");
          navToggle.setAttribute("aria-expanded", String(isOpen));
          navToggle.textContent = isOpen ? "Hide Sections" : "Sections";
        });
        sideNav.addEventListener("click", (event) => {
          if (
            event.target.matches("[data-settings-tab]") &&
            mobileQuery.matches
          ) {
            sideNav.classList.remove("is-open");
            navToggle.setAttribute("aria-expanded", "false");
            navToggle.textContent = "Sections";
          }
        });
      }

      const logsToggle = document.getElementById("settingsLogsToggle");
      const logsPanel = document.querySelector(".logs-panel");
      if (logsToggle && logsPanel) {
        logsToggle.addEventListener("click", () => {
          const isOpen = logsPanel.classList.toggle("is-open");
          if (isOpen) {
            logsPanel.removeAttribute("hidden");
            // The logs panel now lives inside the "maintenance" tab and the
            // "observability" collapsible (handoff parity layout). The floating
            // "Show live logs" button needs to activate the tab and expand the
            // collapsible so the viewer is actually rendered.
            const parentTab = logsPanel.closest("[data-settings-panel]");
            if (parentTab?.dataset.settingsPanel) {
              setActiveTab(parentTab.dataset.settingsPanel);
            }
            const collapsibleContent = logsPanel.closest(".collapsible-content");
            if (
              collapsibleContent &&
              !collapsibleContent.classList.contains("is-open")
            ) {
              const collapsible = collapsibleContent.closest(".collapsible");
              const header = collapsible?.querySelector(".collapsible-header");
              if (header && ui.toggleCollapsible) {
                ui.toggleCollapsible(header);
              } else if (collapsibleContent) {
                collapsibleContent.classList.add("is-open");
                collapsibleContent.removeAttribute("hidden");
              }
            }
          } else {
            logsPanel.setAttribute("hidden", "");
          }
          logsToggle.setAttribute("aria-expanded", String(isOpen));
          logsToggle.textContent = isOpen ? "Hide live logs" : "Show live logs";
          if (isOpen) {
            logsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        });
      }
    }

    return {
      initMobileNav,
      initializeCollapsibles,
      initializeTabs,
      setActiveTab,
    };
  }

  settingsModules.createNavigationModule = createNavigationModule;
})();

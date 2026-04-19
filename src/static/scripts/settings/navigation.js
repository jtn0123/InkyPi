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
          logsToggle.textContent = isOpen ? "Hide Logs" : "Show Logs";
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

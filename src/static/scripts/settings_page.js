(function () {
  function requireSettingsFactory(settingsModules, name) {
    const factory = settingsModules?.[name];
    if (typeof factory !== "function") {
      throw new TypeError(`Missing settings module factory: ${name}`);
    }
    return factory;
  }

  function createSettingsPage(config) {
    const ui = globalThis.InkyPiUI || {};
    const mobileQuery = globalThis.matchMedia
      ? globalThis.matchMedia("(max-width: 768px)")
      : { matches: false, addEventListener() {} };

    // Shared mutable page state, passed by reference to every settings module.
    const state = {
      logsAutoScroll: true,
      logsWrap: true,
      lastLogsRaw: "",
      logsUpdatedAt: "",
      attachGeo: false,
      activeTab: "device",
    };

    const settingsModules = globalThis.InkyPiSettingsModules || {};
    const shared = settingsModules.shared || {};
    const formModule = requireSettingsFactory(
      settingsModules,
      "createFormModule"
    )({ config, state, shared });
    const modalModule = requireSettingsFactory(
      settingsModules,
      "createModalModule"
    )();
    const logsModule = requireSettingsFactory(
      settingsModules,
      "createLogsModule"
    )({ config, state, ui, shared });
    const diagnosticsModule = requireSettingsFactory(
      settingsModules,
      "createDiagnosticsModule"
    )({ ui, modals: modalModule });
    const navigationModule = requireSettingsFactory(
      settingsModules,
      "createNavigationModule"
    )({ state, ui, mobileQuery });
    // Follows an update or rollback to the end; when it ends, the version
    // check runs again so the panel shows what is installed now.
    const trackerModule = requireSettingsFactory(
      settingsModules,
      "createUpdateTrackerModule"
    )({
      config,
      shared,
      logs: logsModule,
      onFinished: () => actionsModule.checkForUpdates({ silent: true }),
    });
    const actionsModule = requireSettingsFactory(
      settingsModules,
      "createActionsModule"
    )({ config, modals: modalModule, tracker: trackerModule });

    function syncProgressStreamForTab(tab) {
      if (tab === "maintenance") {
        diagnosticsModule.initProgressSSE();
      } else if (diagnosticsModule.stopProgressSSE) {
        diagnosticsModule.stopProgressSSE();
      }
    }

    // Show a message an action stored before reloading the page (Safe reset).
    function restoreStoredMessage() {
      let stored = null;
      try {
        stored = sessionStorage.getItem("storedMessage");
        sessionStorage.removeItem("storedMessage");
      } catch (e) {
        console.debug("Stored message unavailable:", e);
        return;
      }
      if (!stored) return;
      try {
        const { type, text } = JSON.parse(stored);
        if (text) showResponseModal(type, text);
      } catch (e) {
        console.debug("Invalid stored message:", e);
      }
    }

    function init() {
      restoreStoredMessage();
      formModule.populateIntervalFields();
      formModule.bind();
      actionsModule.bind();
      trackerModule.bind();
      diagnosticsModule.bind();
      document.addEventListener("settingsTabChanged", (event) =>
        syncProgressStreamForTab(event.detail?.tab)
      );
      navigationModule.initializeTabs();
      logsModule.initializeControls();
      navigationModule.initializeCollapsibles();
      navigationModule.initMobileNav();
      modalModule.bindGlobalDismissals();
      diagnosticsModule.refreshBenchmarks();
      diagnosticsModule.refreshHealth();
      diagnosticsModule.refreshIsolation();
      syncProgressStreamForTab(state.activeTab);
      actionsModule.hydrateVersionCheckFromCache();
      setTimeout(() => actionsModule.checkForUpdates({ silent: true }), 5000);
      trackerModule.resume();
      if (mobileQuery && typeof mobileQuery.addEventListener === "function") {
        mobileQuery.addEventListener("change", () =>
          navigationModule.setActiveTab(state.activeTab)
        );
      }
      const teardown = () => {
        trackerModule.pause();
        diagnosticsModule.teardown();
      };
      globalThis.addEventListener("beforeunload", teardown);
      globalThis.addEventListener("pagehide", teardown);
      globalThis.addEventListener("pageshow", (event) => {
        if (event.persisted) {
          syncProgressStreamForTab(state.activeTab);
          void trackerModule.resume();
        }
      });
    }

    Object.assign(globalThis, {
      checkForUpdates: actionsModule.checkForUpdates,
      exportConfig: actionsModule.exportConfig,
      handleAction: formModule.handleAction,
      handleShutdown: actionsModule.handleShutdown,
      importConfig: actionsModule.importConfig,
      isolatePlugin: diagnosticsModule.isolatePlugin,
      jumpToSection: ui.jumpToSection,
      manualLogsRefresh: logsModule.manualLogsRefresh,
      refreshBenchmarks: diagnosticsModule.refreshBenchmarks,
      refreshHealth: diagnosticsModule.refreshHealth,
      refreshIsolation: diagnosticsModule.refreshIsolation,
      safeReset: diagnosticsModule.safeReset,
      startUpdate: actionsModule.startUpdate,
      toggleUseDeviceLocation: formModule.toggleUseDeviceLocation,
      unIsolatePlugin: diagnosticsModule.unIsolatePlugin,
      updateSliderValue: formModule.updateSliderValue,
    });

    return { init };
  }

  globalThis.InkyPiSettingsPage = { create: createSettingsPage };
})();

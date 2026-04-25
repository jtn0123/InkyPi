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

    const store = globalThis.InkyPiStore
      ? globalThis.InkyPiStore.createStore({
          logsAutoScroll: true,
          logsWrap: true,
          lastLogsRaw: "",
          updateTimer: null,
          attachGeo: false,
          activeTab: "device",
        })
      : null;

    const stateFallback = {
      logsAutoScroll: true,
      logsWrap: true,
      lastLogsRaw: "",
      updateTimer: null,
      attachGeo: false,
      activeTab: "device",
    };

    const state = new Proxy(stateFallback, {
      get(target, key) {
        return store ? store.get(key) : target[key];
      },
      set(target, key, value) {
        if (store) {
          store.set({ [key]: value });
        } else {
          target[key] = value;
        }
        return true;
      },
    });

    const settingsModules = globalThis.InkyPiSettingsModules || {};
    const shared = settingsModules.shared || {};
    const formModule = requireSettingsFactory(
      settingsModules,
      "createFormModule"
    )({ config, state, shared });
    const modalModule = requireSettingsFactory(
      settingsModules,
      "createModalModule"
    )({ ui });
    const logsModule = requireSettingsFactory(
      settingsModules,
      "createLogsModule"
    )({ config, state, ui, shared });
    const diagnosticsModule = requireSettingsFactory(
      settingsModules,
      "createDiagnosticsModule"
    )({ ui });
    const navigationModule = requireSettingsFactory(
      settingsModules,
      "createNavigationModule"
    )({ state, ui, mobileQuery });
    const actionsModule = requireSettingsFactory(
      settingsModules,
      "createActionsModule"
    )({ config, state, shared, logs: logsModule, modals: modalModule });

    function syncProgressStreamForTab(tab) {
      if (tab === "maintenance") {
        diagnosticsModule.initProgressSSE();
      } else if (diagnosticsModule.stopProgressSSE) {
        diagnosticsModule.stopProgressSSE();
      }
    }

    function init() {
      formModule.populateIntervalFields();
      formModule.bind();
      actionsModule.bind();
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
      actionsModule.refreshUpdateStatus();
      if (mobileQuery && typeof mobileQuery.addEventListener === "function") {
        mobileQuery.addEventListener("change", () =>
          navigationModule.setActiveTab(state.activeTab)
        );
      }
      const teardown = () => {
        actionsModule.stop();
        diagnosticsModule.teardown();
      };
      globalThis.addEventListener("beforeunload", teardown);
      globalThis.addEventListener("pagehide", teardown);
      globalThis.addEventListener("pageshow", (event) => {
        if (event.persisted) {
          syncProgressStreamForTab(state.activeTab);
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

(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function updateLastUpdated() {
    const el = document.getElementById("logsUpdated");
    if (el) {
      el.textContent = `Updated ${new Date().toLocaleTimeString()}`;
    }
  }

  function isViewerAtBottom(viewer) {
    return viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 8;
  }

  function flashLogsViewer() {
    const viewer = document.getElementById("logsViewer");
    if (!viewer) return;
    viewer.style.boxShadow = "0 0 0 2px var(--accent)";
    setTimeout(() => {
      viewer.style.boxShadow = "";
    }, 500);
  }

  function buildLogsParams(hoursSelect, levelSelect, filterInput, maxLinesInput) {
    const params = new URLSearchParams();
    params.set("hours", String(hoursSelect?.value || "2"));
    params.set("level", levelSelect?.value || "all");
    if (filterInput?.value) {
      params.set("contains", filterInput.value);
    }
    if (maxLinesInput) {
      params.set(
        "limit",
        String(Math.max(50, Number.parseInt(maxLinesInput.value || "500", 10)))
      );
    }
    return params;
  }

  function setToggleButtonState(btn, isOn, onLabel, offLabel) {
    if (!btn) return;
    btn.textContent = isOn ? onLabel : offLabel;
    btn.setAttribute("aria-pressed", String(isOn));
  }

  function restoreLogsPreferences(ui, controls) {
    if (controls.filterInput && ui.loadPref) {
      controls.filterInput.value = ui.loadPref("", controls.prefKey("filter"), "");
    }
    if (controls.levelSelect && ui.loadPref) {
      controls.levelSelect.value = ui.loadPref(
        "",
        controls.prefKey("level"),
        "all"
      );
    }
    if (controls.hours && ui.loadPref) {
      controls.hours.value = ui.loadPref("", controls.prefKey("hours"), "2");
    }
    if (controls.maxLinesInput && ui.loadPref) {
      controls.maxLinesInput.value = ui.loadPref(
        "",
        controls.prefKey("maxLines"),
        "500"
      );
    }
  }

  function syncLogsUiState(state, controls) {
    setToggleButtonState(
      controls.autoBtn,
      state.logsAutoScroll,
      "Auto-Scroll: On",
      "Auto-Scroll: Off"
    );
    setToggleButtonState(
      controls.wrapBtn,
      state.logsWrap,
      "Wrap: On",
      "Wrap: Off"
    );
    if (controls.viewer) {
      controls.viewer.style.whiteSpace = state.logsWrap ? "pre-wrap" : "pre";
    }
  }

  function bindLogsControlListeners(controls, handlers, ui) {
    if (controls.hours) {
      controls.hours.addEventListener("change", handlers.onLogsControlsChanged);
    }
    if (controls.autoBtn) {
      controls.autoBtn.addEventListener("click", handlers.toggleLogsAutoScroll);
    }
    if (controls.filterInput && ui.debounce) {
      controls.filterInput.addEventListener(
        "input",
        ui.debounce(handlers.onLogsFilterChanged, 200)
      );
    }
    if (controls.levelSelect) {
      controls.levelSelect.addEventListener("change", handlers.onLogsFilterChanged);
    }
    if (controls.maxLinesInput) {
      controls.maxLinesInput.addEventListener(
        "change",
        handlers.onLogsFilterChanged
      );
    }
    if (controls.refreshBtn) {
      controls.refreshBtn.addEventListener("click", handlers.manualLogsRefresh);
    }
    if (controls.copyBtn) {
      controls.copyBtn.addEventListener("click", handlers.copyLogsToClipboard);
    }
    if (controls.clearBtn) {
      controls.clearBtn.addEventListener("click", handlers.clearLogsView);
    }
    if (controls.wrapBtn) {
      controls.wrapBtn.addEventListener("click", handlers.toggleLogsWrap);
    }
    document
      .getElementById("downloadLogsBtn")
      ?.addEventListener("click", handlers.downloadLogs);
  }

  function createLogsModule({ config, state, ui, shared }) {
    const { copyText, isErrorLine, isWarnLine, prefKey, showCopyFeedback } =
      shared;

    function applyLogFiltersAndRender() {
      const viewer = document.getElementById("logsViewer");
      if (!viewer) return;

      const filterInput = document.getElementById("logsFilter");
      const levelSelect = document.getElementById("logsLevel");
      const maxLinesInput = document.getElementById("logsMaxLines");

      const filterText = (filterInput?.value || "").toLowerCase();
      const level = levelSelect?.value || "all";
      const maxLines = Math.max(
        50,
        Number.parseInt(maxLinesInput?.value || "500", 10)
      );
      const atBottom = isViewerAtBottom(viewer);

      let lines = (state.lastLogsRaw || "").split("\n");
      if (filterText) {
        lines = lines.filter((line) => line.toLowerCase().includes(filterText));
      }
      if (level === "errors") {
        lines = lines.filter(isErrorLine);
      } else if (level === "warn_errors") {
        lines = lines.filter((line) => isErrorLine(line) || isWarnLine(line));
      }
      if (lines.length > maxLines) {
        lines = lines.slice(-maxLines);
      }

      viewer.textContent = lines.join("\n");
      if (state.logsAutoScroll || atBottom) {
        viewer.scrollTop = viewer.scrollHeight;
      }
    }

    async function fetchAndRenderLogs() {
      const viewer = document.getElementById("logsViewer");
      if (!viewer) return;

      const hoursSelect = document.getElementById("logsHours");
      const filterInput = document.getElementById("logsFilter");
      const levelSelect = document.getElementById("logsLevel");
      const maxLinesInput = document.getElementById("logsMaxLines");
      try {
        const params = buildLogsParams(
          hoursSelect,
          levelSelect,
          filterInput,
          maxLinesInput
        );
        const resp = await fetch(`${config.logsUrl}?${params.toString()}`, {
          cache: "no-store",
        });
        const data = await resp.json();
        state.lastLogsRaw = Array.isArray(data?.lines)
          ? data.lines.join("\n")
          : "";
        updateLastUpdated();
        applyLogFiltersAndRender();
        flashLogsViewer();
      } catch (e) {
        console.error("Failed to fetch logs", e);
      }
    }

    function toggleLogsAutoScroll() {
      state.logsAutoScroll = !state.logsAutoScroll;
      setToggleButtonState(
        document.getElementById("logsAutoScrollBtn"),
        state.logsAutoScroll,
        "Auto-Scroll: On",
        "Auto-Scroll: Off"
      );
      ui.savePref?.("", prefKey("autoScroll"), state.logsAutoScroll);
    }

    function onLogsControlsChanged() {
      const hours = document.getElementById("logsHours");
      const maxLines = document.getElementById("logsMaxLines");
      if (hours && ui.savePref) ui.savePref("", prefKey("hours"), hours.value);
      if (maxLines && ui.savePref) {
        ui.savePref("", prefKey("maxLines"), maxLines.value);
      }
      fetchAndRenderLogs();
    }

    function onLogsFilterChanged() {
      const filterInput = document.getElementById("logsFilter");
      const levelSelect = document.getElementById("logsLevel");
      if (filterInput && ui.savePref) {
        ui.savePref("", prefKey("filter"), filterInput.value || "");
      }
      if (levelSelect && ui.savePref) {
        ui.savePref("", prefKey("level"), levelSelect.value || "all");
      }
      applyLogFiltersAndRender();
    }

    async function manualLogsRefresh() {
      const btn = document.getElementById("logsRefreshBtn");
      const updated = document.getElementById("logsUpdated");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Refreshing...";
      }
      if (updated) updated.textContent = "Refreshing...";
      try {
        await fetchAndRenderLogs();
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Refresh";
        }
      }
    }

    async function copyLogsToClipboard() {
      const viewer = document.getElementById("logsViewer");
      const copyBtn = document.getElementById("logsCopyBtn");
      if (!viewer) return;
      const ok = await copyText(viewer.textContent || "");
      showCopyFeedback(copyBtn, ok);
    }

    function clearLogsView() {
      const viewer = document.getElementById("logsViewer");
      if (viewer) viewer.textContent = "";
      state.lastLogsRaw = "";
      const filterInput = document.getElementById("logsFilter");
      const levelSelect = document.getElementById("logsLevel");
      if (filterInput) filterInput.value = "";
      if (levelSelect) levelSelect.value = "all";
      if (ui.savePref) {
        ui.savePref("", prefKey("filter"), "");
        ui.savePref("", prefKey("level"), "all");
      }
      showResponseModal("success", "Log view cleared");
    }

    async function downloadLogs() {
      const btn = document.getElementById("downloadLogsBtn");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Downloading…";
      }
      try {
        const resp = await fetch(config.downloadLogsUrl, { cache: "no-store" });
        if (!resp.ok) {
          showResponseModal("failure", "Failed to download logs");
          return;
        }
        const text = await resp.text();
        if (!text || text.trim().length === 0) {
          showResponseModal("failure", "No logs available to download");
          return;
        }
        const disposition = resp.headers.get("Content-Disposition") || "";
        const filenameRe = /filename=([^\s;]+)/;
        const match = filenameRe.exec(disposition);
        const filename = match ? match[1] : "inkypi_logs.log";
        const blob = new Blob([text], { type: "text/plain" });
        const anchor = document.createElement("a");
        anchor.href = URL.createObjectURL(blob);
        anchor.download = filename;
        anchor.click();
        URL.revokeObjectURL(anchor.href);
        showResponseModal("success", "Logs downloaded");
      } catch (e) {
        console.warn("Failed to download logs:", e);
        showResponseModal("failure", "Failed to download logs");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Download Logs";
        }
      }
    }

    function toggleLogsWrap() {
      state.logsWrap = !state.logsWrap;
      const viewer = document.getElementById("logsViewer");
      if (viewer) viewer.style.whiteSpace = state.logsWrap ? "pre-wrap" : "pre";
      setToggleButtonState(
        document.getElementById("logsWrapBtn"),
        state.logsWrap,
        "Wrap: On",
        "Wrap: Off"
      );
      ui.savePref?.("", prefKey("wrap"), state.logsWrap);
    }

    function initializeControls() {
      const controls = {
        autoBtn: document.getElementById("logsAutoScrollBtn"),
        clearBtn: document.getElementById("logsClearBtn"),
        copyBtn: document.getElementById("logsCopyBtn"),
        filterInput: document.getElementById("logsFilter"),
        hours: document.getElementById("logsHours"),
        maxLinesInput: document.getElementById("logsMaxLines"),
        levelSelect: document.getElementById("logsLevel"),
        prefKey,
        refreshBtn: document.getElementById("logsRefreshBtn"),
        viewer: document.getElementById("logsViewer"),
        wrapBtn: document.getElementById("logsWrapBtn"),
      };

      restoreLogsPreferences(ui, controls);
      state.logsAutoScroll =
        ui.loadPref?.("", prefKey("autoScroll"), "true") === "true";
      state.logsWrap = ui.loadPref?.("", prefKey("wrap"), "true") === "true";
      syncLogsUiState(state, controls);
      bindLogsControlListeners(
        controls,
        {
          clearLogsView,
          copyLogsToClipboard,
          downloadLogs,
          manualLogsRefresh,
          onLogsControlsChanged,
          onLogsFilterChanged,
          toggleLogsAutoScroll,
          toggleLogsWrap,
        },
        ui
      );
      fetchAndRenderLogs();
    }

    return {
      applyLogFiltersAndRender,
      copyLogsToClipboard,
      downloadLogs,
      fetchAndRenderLogs,
      initializeControls,
      manualLogsRefresh,
      toggleLogsAutoScroll,
      toggleLogsWrap,
    };
  }

  settingsModules.createLogsModule = createLogsModule;
})();

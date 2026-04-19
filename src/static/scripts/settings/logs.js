(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function createLogsModule({ config, state, ui, shared }) {
    const {
      copyViaExecCommand,
      isErrorLine,
      isWarnLine,
      prefKey,
      showCopyFeedback,
    } = shared;

    function updateLastUpdated() {
      const el = document.getElementById("logsUpdated");
      if (el) {
        el.textContent = `Updated ${new Date().toLocaleTimeString()}`;
      }
    }

    function isViewerAtBottom(viewer) {
      return viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 8;
    }

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
        lines = lines.filter((line) =>
          line.toLowerCase().includes(filterText)
        );
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

    function flashLogsViewer() {
      const viewer = document.getElementById("logsViewer");
      if (!viewer) return;
      viewer.style.boxShadow = "0 0 0 2px var(--accent)";
      setTimeout(() => {
        viewer.style.boxShadow = "";
      }, 500);
    }

    async function fetchAndRenderLogs() {
      const hoursSelect = document.getElementById("logsHours");
      const viewer = document.getElementById("logsViewer");
      if (!viewer) return;
      try {
        const filterInput = document.getElementById("logsFilter");
        const levelSelect = document.getElementById("logsLevel");
        const maxLinesInput = document.getElementById("logsMaxLines");
        const params = new URLSearchParams();
        params.set("hours", String(hoursSelect ? hoursSelect.value : "2"));
        if (levelSelect) params.set("level", levelSelect.value || "all");
        if (filterInput?.value) {
          params.set("contains", filterInput.value);
        }
        if (maxLinesInput) {
          params.set(
            "limit",
            String(
              Math.max(50, Number.parseInt(maxLinesInput.value || "500", 10))
            )
          );
        }
        const resp = await fetch(`${config.logsUrl}?${params.toString()}`, {
          cache: "no-store",
        });
        const data = await resp.json();
        state.lastLogsRaw =
          data && Array.isArray(data.lines) ? data.lines.join("\n") : "";
        updateLastUpdated();
        applyLogFiltersAndRender();
        flashLogsViewer();
      } catch (e) {
        console.error("Failed to fetch logs", e);
      }
    }

    function toggleLogsAutoScroll() {
      state.logsAutoScroll = !state.logsAutoScroll;
      const btn = document.getElementById("logsAutoScrollBtn");
      if (btn) {
        btn.textContent = state.logsAutoScroll
          ? "Auto-Scroll: On"
          : "Auto-Scroll: Off";
        btn.setAttribute("aria-pressed", String(state.logsAutoScroll));
      }
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

    function copyLogsToClipboard() {
      const viewer = document.getElementById("logsViewer");
      const copyBtn = document.getElementById("logsCopyBtn");
      if (!viewer) return;
      const text = viewer.textContent || "";

      if (navigator.clipboard && globalThis.isSecureContext) {
        const onSuccess = () => showCopyFeedback(copyBtn, true);
        const onFailure = () => showCopyFeedback(copyBtn, false);
        navigator.clipboard.writeText(text).then(onSuccess, onFailure);
      } else {
        showCopyFeedback(copyBtn, copyViaExecCommand(text));
      }
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
        btn.textContent = "Downloading\u2026";
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
      } catch (_e) {
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
      const btn = document.getElementById("logsWrapBtn");
      if (viewer) viewer.style.whiteSpace = state.logsWrap ? "pre-wrap" : "pre";
      if (btn) {
        btn.textContent = state.logsWrap ? "Wrap: On" : "Wrap: Off";
        btn.setAttribute("aria-pressed", String(state.logsWrap));
      }
      ui.savePref?.("", prefKey("wrap"), state.logsWrap);
    }

    function initializeControls() {
      const hours = document.getElementById("logsHours");
      const autoBtn = document.getElementById("logsAutoScrollBtn");
      const filterInput = document.getElementById("logsFilter");
      const levelSelect = document.getElementById("logsLevel");
      const maxLinesInput = document.getElementById("logsMaxLines");
      const refreshBtn = document.getElementById("logsRefreshBtn");
      const copyBtn = document.getElementById("logsCopyBtn");
      const clearBtn = document.getElementById("logsClearBtn");
      const wrapBtn = document.getElementById("logsWrapBtn");
      const viewer = document.getElementById("logsViewer");

      if (filterInput && ui.loadPref) {
        filterInput.value = ui.loadPref("", prefKey("filter"), "");
      }
      if (levelSelect && ui.loadPref) {
        levelSelect.value = ui.loadPref("", prefKey("level"), "all");
      }
      if (hours && ui.loadPref) {
        hours.value = ui.loadPref("", prefKey("hours"), "2");
      }
      if (maxLinesInput && ui.loadPref) {
        maxLinesInput.value = ui.loadPref("", prefKey("maxLines"), "500");
      }

      state.logsAutoScroll =
        ui.loadPref?.("", prefKey("autoScroll"), "true") === "true";
      state.logsWrap = ui.loadPref?.("", prefKey("wrap"), "true") === "true";
      if (autoBtn) {
        autoBtn.textContent = state.logsAutoScroll
          ? "Auto-Scroll: On"
          : "Auto-Scroll: Off";
        autoBtn.setAttribute("aria-pressed", String(state.logsAutoScroll));
      }
      if (wrapBtn) {
        wrapBtn.textContent = state.logsWrap ? "Wrap: On" : "Wrap: Off";
        wrapBtn.setAttribute("aria-pressed", String(state.logsWrap));
      }
      if (viewer) {
        viewer.style.whiteSpace = state.logsWrap ? "pre-wrap" : "pre";
      }

      if (hours) hours.addEventListener("change", onLogsControlsChanged);
      if (autoBtn) autoBtn.addEventListener("click", toggleLogsAutoScroll);
      if (filterInput && ui.debounce) {
        filterInput.addEventListener(
          "input",
          ui.debounce(onLogsFilterChanged, 200)
        );
      }
      if (levelSelect) levelSelect.addEventListener("change", onLogsFilterChanged);
      if (maxLinesInput) {
        maxLinesInput.addEventListener("change", onLogsFilterChanged);
      }
      if (refreshBtn) refreshBtn.addEventListener("click", manualLogsRefresh);
      if (copyBtn) copyBtn.addEventListener("click", copyLogsToClipboard);
      if (clearBtn) clearBtn.addEventListener("click", clearLogsView);
      if (wrapBtn) wrapBtn.addEventListener("click", toggleLogsWrap);
      document
        .getElementById("downloadLogsBtn")
        ?.addEventListener("click", downloadLogs);
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

(function () {
  function showCopyFeedback(btn, success) {
    if (!btn) return;
    const original = btn.textContent;
    btn.textContent = success ? "Copied!" : "Copy failed";
    setTimeout(() => {
      btn.textContent = original;
    }, 1500);
  }

  function copyViaExecCommand(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      console.warn("execCommand copy not supported:", e);
    }
    ta.remove();
    return ok;
  }

  function getFormSnapshot(form) {
    const target = form || document.querySelector(".settings-form");
    if (!target) return {};
    const snap = {};
    for (const el of target.querySelectorAll("input, select, textarea")) {
      const key = el.name || el.id;
      if (!key) continue;
      snap[key] = el.type === "checkbox" ? el.checked : el.value;
    }
    return snap;
  }

  function restoreFormFromSnapshot(form, snapshot) {
    if (!form || !snapshot) return;
    for (const el of form.querySelectorAll("input, select, textarea")) {
      const key = el.name || el.id;
      if (!key || !(key in snapshot)) continue;
      if (el.type === "checkbox") {
        el.checked = snapshot[key];
      } else {
        el.value = snapshot[key];
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  function isErrorLine(line) {
    return /\b(ERROR|CRITICAL|Exception|Traceback)\b/i.test(line);
  }

  function isWarnLine(line) {
    return /\bWARNING\b/i.test(line);
  }

  function prefKey(key) {
    return `logs_${key}`;
  }

  function createSettingsPage(config) {
    const ui = globalThis.InkyPiUI || {};
    const mobileQuery = globalThis.matchMedia ? globalThis.matchMedia("(max-width: 768px)") : { matches: false, addEventListener() {} };

    // Use InkyPiStore for UI state when available (JTN-502)
    const _store = globalThis.InkyPiStore
      ? globalThis.InkyPiStore.createStore({
          logsAutoScroll: true,
          logsWrap: true,
          lastLogsRaw: "",
          updateTimer: null,
          attachGeo: false,
          activeTab: "device",
        })
      : null;

    // Plain fallback object — used directly when store is not loaded.
    const _stateFallback = {
      logsAutoScroll: true,
      logsWrap: true,
      lastLogsRaw: "",
      updateTimer: null,
      attachGeo: false,
      activeTab: "device",
    };

    // Proxy that reads/writes through the store when available.
    const state = new Proxy(_stateFallback, {
      get(target, key) {
        return _store ? _store.get(key) : target[key];
      },
      set(target, key, value) {
        if (_store) { _store.set({ [key]: value }); } else { target[key] = value; }
        return true;
      },
    });

    function populateIntervalFields() {
      const intervalInput = document.getElementById("interval");
      const unitSelect = document.getElementById("unit");
      const seconds = config.pluginCycleIntervalSeconds;
      if (!intervalInput || !unitSelect || seconds == null) return;
      const intervalInMinutes = Math.floor(seconds / 60);
      const intervalInHours = Math.floor(seconds / 3600);
      if (intervalInHours > 0) {
        intervalInput.value = String(intervalInHours);
        unitSelect.value = "hour";
      } else {
        intervalInput.value = String(Math.max(1, intervalInMinutes));
        unitSelect.value = "minute";
      }
    }

    // Dirty-state tracking for the Save button
    let _formSnapshot = null;

    function isFormValid() {
      const form = document.querySelector(".settings-form");
      if (!form || typeof form.checkValidity !== "function") return true;
      return form.checkValidity();
    }

    function checkDirty() {
      const saveBtn = document.getElementById("saveSettingsBtn");
      if (!saveBtn || !_formSnapshot) return;
      const current = getFormSnapshot();
      let dirty = false;
      const allKeys = new Set([...Object.keys(_formSnapshot), ...Object.keys(current)]);
      for (const key of allKeys) {
        if (_formSnapshot[key] !== current[key]) { dirty = true; break; }
      }
      // JTN-350: Save must be enabled only when the form is BOTH dirty AND
      // satisfies all HTML5 constraints (required, min, max, etc.). This
      // prevents users from clicking Save with `deviceName` empty or
      // `interval=-5` and only learning about the problem from server toasts.
      saveBtn.disabled = !(dirty && isFormValid());
    }

    async function appendGeoData(formData) {
      if (!state.attachGeo || !navigator.geolocation) return;
      try {
        const pos = await new Promise((resolve, reject) =>
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            maximumAge: 60000,
            timeout: 4000,
          })
        );
        if (pos?.coords) {
          formData.set("deviceLat", String(pos.coords.latitude));
          formData.set("deviceLon", String(pos.coords.longitude));
        }
      } catch (e) {
        console.warn("Geolocation unavailable:", e.message || e);
      }
    }

    async function handleAction() {
      const form = document.querySelector(".settings-form");
      const saveBtn = document.getElementById("saveSettingsBtn");
      // JTN-350: Always enforce HTML5 constraint validation before contacting
      // the server. Even if the Save button slipped through the disabled
      // gate (e.g. dispatched programmatically), reportValidity() shows the
      // browser's native :invalid popup and focuses the first invalid field.
      if (form && typeof form.checkValidity === "function" && !form.checkValidity()) {
        if (typeof form.reportValidity === "function") form.reportValidity();
        const firstInvalid = form.querySelector(":invalid");
        if (firstInvalid && typeof firstInvalid.focus === "function") {
          firstInvalid.focus();
        }
        return;
      }
      if (saveBtn?.disabled) {
        showResponseModal("success", "No changes to save.");
        return;
      }
      // JTN-505: FormState owns the disabled/aria-busy/spinner lifecycle.
      const fs = (globalThis.FormState && form) ? globalThis.FormState.attach(form) : null;
      if (fs) fs.clearErrors();
      const formData = new FormData(form);
      await appendGeoData(formData);

      const doSubmit = async () => {
        try {
          const response = await fetch(config.saveSettingsUrl, {
            method: "POST",
            body: formData,
          });
          const result = await response.json();
          if (response.ok) {
            _formSnapshot = getFormSnapshot(form);
            if (saveBtn) saveBtn.disabled = true;
            showResponseModal("success", `Success! ${result.message}`);
          } else {
            // Surface field-level errors inline when the server returns them.
            if (fs && result && result.field_errors && typeof result.field_errors === "object") {
              fs.setFieldErrors(result.field_errors);
            }
            showResponseModal("failure", `Error! ${result.error}`);
            restoreFormFromSnapshot(form, _formSnapshot);
          }
        } catch (error) {
          console.error("Settings save failed:", error);
          showResponseModal(
            "failure",
            "An error occurred while processing your request. Please try again."
          );
          checkDirty();
        }
      };

      if (fs) {
        await fs.run(doSubmit);
      } else {
        // Fallback path for environments without FormState (should not occur).
        if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "Saving\u2026"; }
        try { await doSubmit(); } finally {
          if (saveBtn?.textContent === "Saving\u2026") saveBtn.textContent = "Save";
        }
      }
    }

    // JTN-652: Track the element that triggered the most-recently opened
    // confirmation modal so focus can be restored when the modal closes
    // (WAI-ARIA best practice — sibling of JTN-461/463 for the plugin page
    // scheduleModal).
    let _lastDeviceActionTrigger = null;

    function setDeviceActionModalOpen(modalId, open, triggerEl) {
      const modal = document.getElementById(modalId);
      if (!modal) return;
      if (open && triggerEl) _lastDeviceActionTrigger = triggerEl;
      modal.hidden = !open;
      modal.style.display = open ? "flex" : "none";
      modal.classList.toggle("is-open", !!open);
      // Keep body.modal-open in sync so backdrop/scroll-lock CSS fires.
      const ui = globalThis.InkyPiUI;
      if (ui?.syncModalOpenState) {
        ui.syncModalOpenState();
      } else {
        const anyOpen = document.querySelector(".modal.is-open");
        document.body.classList.toggle("modal-open", !!anyOpen);
      }
      if (open) {
        // JTN-652: move focus into the modal on open so keyboard + screen
        // reader users land somewhere inside the dialog.
        const focusable = modal.querySelector(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusable) setTimeout(() => focusable.focus(), 0);
      } else if (_lastDeviceActionTrigger) {
        // JTN-652: restore focus to the trigger so the user is returned to
        // the button they came from rather than being dumped on <body>.
        try { _lastDeviceActionTrigger.focus(); } catch (_e) { /* ignore */ }
        _lastDeviceActionTrigger = null;
      }
    }

    function openRebootConfirm(event) {
      setDeviceActionModalOpen("rebootConfirmModal", true, event?.currentTarget);
    }

    function closeRebootConfirm() {
      setDeviceActionModalOpen("rebootConfirmModal", false);
    }

    function openShutdownConfirm(event) {
      setDeviceActionModalOpen("shutdownConfirmModal", true, event?.currentTarget);
    }

    function closeShutdownConfirm() {
      setDeviceActionModalOpen("shutdownConfirmModal", false);
    }

    function isDeviceActionModalOpen(modalId) {
      const modal = document.getElementById(modalId);
      return !!(modal && !modal.hidden);
    }

    async function handleShutdown(reboot) {
      // JTN-621: callers must gate this behind a confirmation modal. The
      // modal ensures an accidental tap on a touch screen doesn't make the
      // device unreachable without physical access to recover.
      if (reboot) {
        closeRebootConfirm();
      } else {
        closeShutdownConfirm();
      }
      showResponseModal(
        "success",
        reboot
          ? "The system is rebooting. The UI will be unavailable until the reboot is complete."
          : "The system is shutting down. The UI will remain unavailable until it is manually restarted."
      );
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try {
        await fetch(config.shutdownUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reboot }),
        });
      } catch (e) {
        // Expected — device is shutting down, connection will be severed
      }
    }

    function toggleUseDeviceLocation(cb) {
      state.attachGeo = !!(cb?.checked);
    }

    function updateLastUpdated() {
      const el = document.getElementById("logsUpdated");
      if (el) {
        el.textContent = `Updated ${new Date().toLocaleTimeString()}`;
      }
    }

    function isViewerAtBottom(viewer) {
      return (
        viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 8
      );
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
            String(Math.max(50, Number.parseInt(maxLinesInput.value || "500", 10)))
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
      if (btn) { btn.disabled = true; btn.textContent = "Downloading\u2026"; }
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
        if (btn) { btn.disabled = false; btn.textContent = "Download Logs"; }
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

    async function checkForUpdates() {
      const badge = document.getElementById("updateBadge");
      const latestEl = document.getElementById("latestVersion");
      const updateBtn = document.getElementById("startUpdateBtn");
      const checkBtn = document.getElementById("checkUpdatesBtn");
      const notesContainer = document.getElementById("releaseNotesContainer");
      const notesBody = document.getElementById("releaseNotesBody");

      // Show spinner + disable button while checking (JTN-352)
      if (checkBtn) {
        checkBtn.disabled = true;
        const sp = checkBtn.querySelector(".btn-spinner");
        if (sp) sp.style.display = "inline-block";
      }
      if (badge) { badge.textContent = "Checking..."; badge.className = "status-chip"; }
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000);
        const resp = await fetch(config.versionUrl, { cache: "no-store", signal: controller.signal });
        clearTimeout(timeoutId);
        const data = await resp.json();
        if (latestEl) latestEl.textContent = data.latest || "\u2014";
        if (data.update_available) {
          if (badge) { badge.textContent = "Update available"; badge.className = "status-chip warning"; }
          if (updateBtn) updateBtn.disabled = false;
        } else if (data.latest) {
          if (badge) { badge.textContent = "Up to date"; badge.className = "status-chip success"; }
          if (updateBtn) updateBtn.disabled = true;
        } else {
          if (badge) { badge.textContent = "Unable to check"; badge.className = "status-chip"; }
        }
        // Populate release notes if available
        if (data.release_notes && notesContainer && notesBody) {
          notesBody.textContent = data.release_notes;
          notesContainer.hidden = false;
        } else if (notesContainer) {
          notesContainer.hidden = true;
        }
      } catch (e) {
        console.warn("Version check failed:", e);
        if (badge) { badge.textContent = "Check failed"; badge.className = "status-chip"; }
      } finally {
        // Re-enable button and hide spinner (JTN-352)
        if (checkBtn) {
          checkBtn.disabled = false;
          const sp = checkBtn.querySelector(".btn-spinner");
          if (sp) sp.style.display = "none";
        }
      }
    }

    async function startUpdate() {
      const btns = document.querySelectorAll(".header-actions .header-button");
      try {
        for (const btn of btns) {
          btn.disabled = true;
        }
        const resp = await fetch(config.startUpdateUrl, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showResponseModal("failure", data.error || "Failed to start update");
          return;
        }
        showResponseModal("success", data.message || "Update started.");
        if (state.updateTimer) clearInterval(state.updateTimer);
        state.updateTimer = setInterval(async () => {
          try {
            await fetchAndRenderLogs();
            const sresp = await fetch(config.updateStatusUrl);
            const sdata = await sresp.json();
            if (!sdata?.running) {
              clearInterval(state.updateTimer);
              state.updateTimer = null;
              setTimeout(fetchAndRenderLogs, 500);
              checkForUpdates();
            }
          } catch (e) {
            console.warn("Update status poll failed:", e);
            clearInterval(state.updateTimer);
            state.updateTimer = null;
          }
        }, 2000);
      } catch (e) {
        console.warn("Failed to start update:", e);
        showResponseModal("failure", "Failed to start update");
      } finally {
        for (const btn of btns) {
          btn.disabled = false;
        }
      }
    }

    async function exportConfig() {
      const btn = document.getElementById("exportConfigBtn");
      if (btn) { btn.disabled = true; btn.textContent = "Downloading\u2026"; }
      const include = document.getElementById("includeKeys")?.checked;
      try {
        const requestInit = include
          ? {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ include_keys: true }),
              cache: "no-store",
            }
          : { cache: "no-store" };
        const resp = await fetch(config.exportSettingsUrl, requestInit);
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showResponseModal("failure", "Export failed");
          return;
        }
        const blob = new Blob([JSON.stringify(data.data, null, 2)], {
          type: "application/json",
        });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `inkypi_backup_${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
        showResponseModal("success", "Backup downloaded");
      } catch (e) {
        console.error("Export failed", e);
        showResponseModal("failure", "Export failed");
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "Download Backup"; }
      }
    }

    async function importConfig() {
      const btn = document.getElementById("importConfigBtn");
      if (btn) { btn.disabled = true; btn.textContent = "Restoring\u2026"; }
      const fileInput = document.getElementById("importFile");
      const file = fileInput?.files?.[0];
      if (!file) {
        showResponseModal("failure", "Choose a backup file first");
        return;
      }
      const form = new FormData();
      form.append("file", file);
      try {
        const resp = await fetch(config.importSettingsUrl, {
          method: "POST",
          body: form,
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showResponseModal("failure", data.error || "Import failed");
          return;
        }
        showResponseModal("success", data.message || "Import complete");
      } catch (e) {
        console.error("Import failed", e);
        showResponseModal("failure", "Import failed");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Restore from File";
        }
        const input = document.getElementById("importFile");
        if (btn) btn.disabled = !input?.files?.length;
      }
    }

    function formatMs(val) {
      if (val === null || val === undefined) return "\u2014";
      const seconds = val / 1000;
      return seconds < 10
        ? seconds.toFixed(1) + "s"
        : Math.round(seconds) + "s";
    }

    const STAGE_LABELS = {
      request_ms: "Request",
      generate_ms: "Generate",
      preprocess_ms: "Preprocess",
      display_ms: "Display",
    };

    function buildSummaryTable(summaryData) {
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      thead.innerHTML =
        "<tr><th>Stage</th><th>p50</th><th>p95</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const [key, label] of Object.entries(STAGE_LABELS)) {
        const row = document.createElement("tr");
        const stage = summaryData[key] || {};
        row.innerHTML =
          "<td>" +
          label +
          "</td><td>" +
          formatMs(stage.p50) +
          "</td><td>" +
          formatMs(stage.p95) +
          "</td>";
        tbody.appendChild(row);
      }
      table.appendChild(tbody);
      return table;
    }

    const PLUGIN_AVG_LABELS = {
      request_avg: "Request",
      generate_avg: "Generate",
      display_avg: "Display",
    };

    function buildPluginsTable(items) {
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      const cols = ["Plugin", "Runs"].concat(
        Object.values(PLUGIN_AVG_LABELS)
      );
      thead.innerHTML =
        "<tr>" + cols.map(function (c) { return "<th>" + c + "</th>"; }).join("") + "</tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      items.slice(0, 10).forEach(function (item) {
        const row = document.createElement("tr");
        const cells = [
          item.plugin_id || "\u2014",
          String(item.runs || 0),
        ];
        for (const key of Object.keys(PLUGIN_AVG_LABELS)) {
          cells.push(formatMs(item[key]));
        }
        row.innerHTML = cells.map(function (c) { return "<td>" + c + "</td>"; }).join("");
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      return table;
    }

    async function refreshBenchmarks() {
      ui.setPanelLoading?.("benchSummary", true);
      try {
        const [summaryResp, pluginsResp] = await Promise.all([
          fetch("/api/benchmarks/summary?window=24h", { cache: "no-store" }),
          fetch("/api/benchmarks/plugins?window=24h", { cache: "no-store" }),
        ]);
        const summary = await summaryResp.json();
        const plugins = await pluginsResp.json();

        const panel = document.getElementById("benchSummary");
        panel.textContent = "";

        const heading1 = document.createElement("strong");
        heading1.textContent = "Benchmark Summary (24h)";
        panel.appendChild(heading1);
        panel.appendChild(buildSummaryTable(summary.summary || {}));

        if ((plugins.items || []).length > 0) {
          const heading2 = document.createElement("strong");
          heading2.textContent = "Per-plugin Averages";
          panel.appendChild(heading2);
          panel.appendChild(buildPluginsTable(plugins.items));
        }
      } catch (e) {
        console.warn("Failed to load benchmark summary:", e);
        document.getElementById("benchSummary").textContent =
          "Failed to load benchmark summary";
      } finally {
        ui.setPanelLoading?.("benchSummary", false);
      }
    }

    function formatPercent(val) {
      if (val === null || val === undefined || Number.isNaN(Number(val))) {
        return "\u2014";
      }
      return Number(val).toFixed(1) + "%";
    }

    function formatUptime(seconds) {
      if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) {
        return "\u2014";
      }
      const total = Math.floor(Number(seconds));
      const days = Math.floor(total / 86400);
      const hours = Math.floor((total % 86400) / 3600);
      const mins = Math.floor((total % 3600) / 60);
      if (days > 0) return days + "d " + hours + "h " + mins + "m";
      if (hours > 0) return hours + "h " + mins + "m";
      return mins + "m";
    }

    const SYSTEM_HEALTH_ROWS = [
      { key: "cpu_percent", label: "CPU", formatter: formatPercent },
      { key: "memory_percent", label: "Memory", formatter: formatPercent },
      { key: "disk_percent", label: "Disk", formatter: formatPercent },
      { key: "uptime_seconds", label: "Uptime", formatter: formatUptime },
    ];

    function buildSystemHealthTable(systemData) {
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Metric</th><th>Value</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const spec of SYSTEM_HEALTH_ROWS) {
        const row = document.createElement("tr");
        const labelCell = document.createElement("td");
        labelCell.textContent = spec.label;
        const valueCell = document.createElement("td");
        valueCell.textContent = spec.formatter(systemData ? systemData[spec.key] : null);
        row.appendChild(labelCell);
        row.appendChild(valueCell);
        tbody.appendChild(row);
      }
      table.appendChild(tbody);
      return table;
    }

    function buildPluginHealthTable(items) {
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Plugin</th><th>Status</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      const entries = Array.isArray(items)
        ? items.map(function (it) {
            return [it.plugin_id || "\u2014", it.status || it.state || "\u2014"];
          })
        : Object.entries(items || {}).map(function (pair) {
            const [pid, info] = pair;
            let status = "\u2014";
            if (info && typeof info === "object") {
              status = info.status || info.state || (info.ok === false ? "error" : "ok");
            } else if (typeof info === "string") {
              status = info;
            }
            return [pid, status];
          });
      if (entries.length === 0) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 2;
        cell.textContent = "No plugin health data";
        row.appendChild(cell);
        tbody.appendChild(row);
      } else {
        entries.forEach(function (pair) {
          const row = document.createElement("tr");
          const pidCell = document.createElement("td");
          pidCell.textContent = pair[0];
          const statusCell = document.createElement("td");
          statusCell.textContent = pair[1];
          row.appendChild(pidCell);
          row.appendChild(statusCell);
          tbody.appendChild(row);
        });
      }
      table.appendChild(tbody);
      return table;
    }

    function buildIsolationTable(isolationData) {
      const list = Array.isArray(isolationData?.isolated_plugins)
        ? isolationData.isolated_plugins
        : [];
      if (list.length === 0) {
        const msg = document.createElement("div");
        msg.className = "bench-empty";
        msg.textContent = "No plugins isolated";
        return msg;
      }
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Plugin</th><th>Isolated</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      list.forEach(function (pluginId) {
        const row = document.createElement("tr");
        const pidCell = document.createElement("td");
        pidCell.textContent = pluginId;
        const statusCell = document.createElement("td");
        statusCell.textContent = "Yes";
        row.appendChild(pidCell);
        row.appendChild(statusCell);
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      return table;
    }

    async function refreshHealth() {
      ui.setPanelLoading?.("healthSummary", true);
      try {
        const [pluginsResp, systemResp] = await Promise.all([
          fetch("/api/health/plugins", { cache: "no-store" }),
          fetch("/api/health/system", { cache: "no-store" }),
        ]);
        const plugins = await pluginsResp.json();
        const system = await systemResp.json();

        const panel = document.getElementById("healthSummary");
        panel.textContent = "";

        const heading1 = document.createElement("strong");
        heading1.textContent = "System Health";
        panel.appendChild(heading1);
        panel.appendChild(buildSystemHealthTable(system || {}));

        const heading2 = document.createElement("strong");
        heading2.textContent = "Plugin Health";
        panel.appendChild(heading2);
        panel.appendChild(buildPluginHealthTable(plugins.items || {}));
      } catch (e) {
        console.warn("Failed to load health data:", e);
        document.getElementById("healthSummary").textContent =
          "Failed to load health data";
      } finally {
        ui.setPanelLoading?.("healthSummary", false);
      }
    }

    async function refreshIsolation() {
      ui.setPanelLoading?.("isolationSummary", true);
      try {
        const resp = await fetch("/settings/isolation", { cache: "no-store" });
        const data = await resp.json();
        const panel = document.getElementById("isolationSummary");
        panel.textContent = "";
        panel.appendChild(buildIsolationTable(data || {}));
      } catch (e) {
        console.warn("Failed to load isolation list:", e);
        document.getElementById("isolationSummary").textContent =
          "Failed to load isolation list";
      } finally {
        ui.setPanelLoading?.("isolationSummary", false);
      }
    }

    async function isolatePlugin() {
      const pluginId = document.getElementById("isolatePluginInput")?.value?.trim();
      if (!pluginId) return;
      try {
        const resp = await fetch("/settings/isolation", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plugin_id: pluginId }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showResponseModal("failure", data.error || "Failed to isolate plugin");
          return;
        }
        await refreshIsolation();
        await refreshHealth();
      } catch (e) {
        console.warn("Failed to isolate plugin:", e);
        showResponseModal("failure", "Failed to isolate plugin");
      }
    }

    async function unIsolatePlugin() {
      const pluginId = document.getElementById("isolatePluginInput")?.value?.trim();
      if (!pluginId) return;
      try {
        const resp = await fetch("/settings/isolation", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plugin_id: pluginId }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showResponseModal("failure", data.error || "Failed to unisolate plugin");
          return;
        }
        await refreshIsolation();
        await refreshHealth();
      } catch (e) {
        console.warn("Failed to unisolate plugin:", e);
        showResponseModal("failure", "Failed to unisolate plugin");
      }
    }

    async function safeReset() {
      try {
        const resp = await fetch("/settings/safe_reset", { method: "POST" });
        const data = await resp.json();
        if (resp.ok && data.success) {
          showResponseModal("success", data.message || "Safe reset complete");
          await refreshHealth();
        } else {
          showResponseModal("failure", data.error || "Safe reset failed");
        }
      } catch (e) {
        console.warn("Safe reset failed:", e);
        showResponseModal("failure", "Safe reset failed");
      }
    }

    let _progressES = null;

    function initProgressSSE() {
      try {
        if (!globalThis.EventSource) return;
        _progressES = new EventSource("/api/progress/stream");
        const refresh = () => refreshHealth();
        _progressES.addEventListener("done", refresh);
        _progressES.addEventListener("error", refresh);
      } catch (e) {
        console.warn("Progress SSE unavailable:", e);
      }
    }

    function initializeLogsControls() {
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
        (ui.loadPref?.("", prefKey("autoScroll"), "true")) === "true";
      state.logsWrap =
        (ui.loadPref?.("", prefKey("wrap"), "true")) === "true";
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
      document.getElementById("downloadLogsBtn")?.addEventListener("click", downloadLogs);
      fetchAndRenderLogs();
    }

    function initializeCollapsibles() {
      if (ui.restoreCollapsibles) {
        ui.restoreCollapsibles(".collapsible-header");
      }
    }

    function setActiveTab(tab) {
      state.activeTab = tab;
      for (const button of document.querySelectorAll("[data-settings-tab]")) {
        const isActive = button.dataset.settingsTab === tab;
        button.classList.toggle("active", isActive);
        if (isActive && mobileQuery.matches) {
          button.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
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
        button.addEventListener("click", () => setActiveTab(button.dataset.settingsTab));
      }
      setActiveTab("device");
    }

    function initializeMobilePanelState() {
      const panel = document.querySelector(`[data-settings-panel="${state.activeTab}"]`);
      if (!panel) return;
      const openSection = panel.querySelector(".collapsible-content.is-open");
      if (openSection) return;
      const firstToggle = panel.querySelector("[data-collapsible-toggle]");
      if (firstToggle && firstToggle.getAttribute("aria-expanded") !== "true" && ui.toggleCollapsible) {
        ui.toggleCollapsible(firstToggle);
      }
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
        // Auto-close nav on tab selection on mobile
        sideNav.addEventListener("click", (e) => {
          if (e.target.matches("[data-settings-tab]") && mobileQuery.matches) {
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

    function bindButtons() {
      // Collapsible toggle is bound via delegation in ui_helpers.js so every
      // `[data-collapsible-toggle]` button updates aria-expanded consistently.

      // Dirty-state: snapshot initial form values and disable Save until something changes
      const saveBtn = document.getElementById("saveSettingsBtn");
      _formSnapshot = getFormSnapshot();
      if (saveBtn) saveBtn.disabled = true;
      const settingsForm = document.querySelector(".settings-form");
      if (settingsForm) {
        settingsForm.addEventListener("input", checkDirty);
        settingsForm.addEventListener("change", checkDirty);
      }

      saveBtn?.addEventListener("click", handleAction);
      document.getElementById("exportConfigBtn")?.addEventListener("click", exportConfig);
      document.getElementById("importConfigBtn")?.addEventListener("click", importConfig);
      const importFileInput = document.getElementById("importFile");
      const importBtn = document.getElementById("importConfigBtn");
      if (importFileInput && importBtn) {
        importFileInput.addEventListener("change", () => {
          importBtn.disabled = !importFileInput.files?.length;
        });
      }
      document.getElementById("refreshBenchmarksBtn")?.addEventListener("click", refreshBenchmarks);
      document.getElementById("safeResetBtn")?.addEventListener("click", safeReset);
      document.getElementById("isolatePluginBtn")?.addEventListener("click", isolatePlugin);
      document.getElementById("unIsolatePluginBtn")?.addEventListener("click", unIsolatePlugin);
      document.getElementById("refreshIsolationBtn")?.addEventListener("click", refreshIsolation);
      document.getElementById("checkUpdatesBtn")?.addEventListener("click", checkForUpdates);
      document.getElementById("startUpdateBtn")?.addEventListener("click", startUpdate);
      // JTN-621: Reboot/Shutdown are gated behind a confirmation modal so
      // an accidental touch doesn't make the device unreachable.
      document.getElementById("rebootBtn")?.addEventListener("click", openRebootConfirm);
      document.getElementById("shutdownBtn")?.addEventListener("click", openShutdownConfirm);
      document.getElementById("confirmRebootBtn")?.addEventListener("click", () => handleShutdown(true));
      document.getElementById("cancelRebootBtn")?.addEventListener("click", closeRebootConfirm);
      document.getElementById("closeRebootConfirmModalBtn")?.addEventListener("click", closeRebootConfirm);
      document.getElementById("confirmShutdownBtn")?.addEventListener("click", () => handleShutdown(false));
      document.getElementById("cancelShutdownBtn")?.addEventListener("click", closeShutdownConfirm);
      document.getElementById("closeShutdownConfirmModalBtn")?.addEventListener("click", closeShutdownConfirm);
      // JTN-652: Escape + backdrop-click dismissal for the reboot / shutdown
      // confirmation modals — parity with every other modal in the app
      // (scheduleModal JTN-461, playlist modals, image lightbox, history
      // modals). Without this the only way to cancel a destructive action
      // via keyboard was to tab to the Cancel button.
      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        if (isDeviceActionModalOpen("rebootConfirmModal")) {
          event.preventDefault();
          closeRebootConfirm();
        } else if (isDeviceActionModalOpen("shutdownConfirmModal")) {
          event.preventDefault();
          closeShutdownConfirm();
        }
      });
      globalThis.addEventListener("click", (event) => {
        const rebootModal = document.getElementById("rebootConfirmModal");
        const shutdownModal = document.getElementById("shutdownConfirmModal");
        if (event.target === rebootModal) closeRebootConfirm();
        else if (event.target === shutdownModal) closeShutdownConfirm();
      });
      document.getElementById("useDeviceLocation")?.addEventListener("change", (event) => {
        toggleUseDeviceLocation(event.currentTarget);
      });
      for (const slider of document.querySelectorAll(".settings-slider")) {
        slider.addEventListener("input", () => {
          const valueDisplay = document.getElementById(`${slider.id}-value`);
          if (valueDisplay) valueDisplay.textContent = Number.parseFloat(slider.value).toFixed(1);
        });
      }
    }

    function init() {
      populateIntervalFields();
      bindButtons();
      initializeTabs();
      initializeLogsControls();
      initializeCollapsibles();
      initMobileNav();
      refreshBenchmarks();
      refreshHealth();
      refreshIsolation();
      initProgressSSE();
      setTimeout(checkForUpdates, 5000);
      if (mobileQuery && typeof mobileQuery.addEventListener === "function") {
        mobileQuery.addEventListener("change", () => setActiveTab(state.activeTab));
      }
      globalThis.addEventListener("beforeunload", () => {
        if (state.updateTimer) {
          clearInterval(state.updateTimer);
          state.updateTimer = null;
        }
        if (_progressES) {
          _progressES.close();
          _progressES = null;
        }
      });
    }

    Object.assign(globalThis, {
      checkForUpdates,
      exportConfig,
      handleAction,
      handleShutdown,
      importConfig,
      isolatePlugin,
      jumpToSection: ui.jumpToSection,
      manualLogsRefresh,
      refreshBenchmarks,
      refreshHealth,
      refreshIsolation,
      safeReset,
      startUpdate,
      toggleUseDeviceLocation,
      unIsolatePlugin,
      updateSliderValue(slider) {
        const valueDisplay = document.getElementById(`${slider.id}-value`);
        if (valueDisplay) {
          valueDisplay.textContent = Number.parseFloat(slider.value).toFixed(1);
        }
      },
    });

    return { init };
  }

  globalThis.InkyPiSettingsPage = { create: createSettingsPage };
})();

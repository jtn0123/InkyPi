(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});
  const VERSION_CACHE_KEY = "inkypi-update-check";
  const VERSION_CACHE_TTL_MS = 10 * 60 * 1000;

  function getCachedVersionData() {
    try {
      const raw = sessionStorage.getItem(VERSION_CACHE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      if (
        typeof parsed.ts !== "number" ||
        Date.now() - parsed.ts > VERSION_CACHE_TTL_MS
      ) {
        return null;
      }
      return parsed.data && typeof parsed.data === "object"
        ? parsed.data
        : null;
    } catch (e) {
      console.warn("Unable to read cached update metadata:", e);
      return null;
    }
  }

  function setCachedVersionData(data) {
    try {
      sessionStorage.setItem(
        VERSION_CACHE_KEY,
        JSON.stringify({ ts: Date.now(), data })
      );
    } catch (e) {
      console.warn("Unable to cache update metadata:", e);
    }
  }

  function getVersionElements() {
    return {
      checkBtn: document.getElementById("checkUpdatesBtn"),
      latestEl: document.getElementById("latestVersion"),
      notesBody: document.getElementById("releaseNotesBody"),
      notesContainer: document.getElementById("releaseNotesContainer"),
      notesVersion: document.getElementById("releaseNotesVersion"),
      updateBtn: document.getElementById("startUpdateBtn"),
      whatsNewBody: document.getElementById("whatsNewBody"),
      whatsNewBtn: document.getElementById("whatsNewBtn"),
    };
  }

  function escapeReleaseNotesHTML(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Minimal markdown → HTML for GitHub release notes. The upstream format
  // is a top-level `# v<ver>` heading (redundant with our version chip),
  // `## <Category>` sections, and `- ` bullets. Everything else becomes
  // a paragraph. Keeping the scope tight avoids pulling in a full parser
  // and makes the output auditable from a unit test.
  function renderReleaseNotesHTML(markdown) {
    if (!markdown || typeof markdown !== "string") return "";
    const lines = markdown.replace(/\r\n/g, "\n").split("\n");
    const out = [];
    let inList = false;
    const flushList = () => {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
    };
    let sawVersionHeading = false;
    for (const raw of lines) {
      const line = raw.trimEnd();
      const trimmed = line.trim();
      if (!trimmed) {
        flushList();
        continue;
      }
      // Hand-rolled bullet / heading detection instead of anchored-greedy
      // regexes to avoid any super-linear backtracking risk (SonarCloud
      // S5852). `trimmed` has no newlines so slice+trim is O(n).
      const firstChar = trimmed.charAt(0);
      if (firstChar === "-" || firstChar === "*" || firstChar === "\u2022") {
        const rest = trimmed.slice(1).replace(/^[ \t]+/, "");
        if (rest && trimmed.charAt(1) !== firstChar) {
          if (!inList) {
            out.push("<ul>");
            inList = true;
          }
          out.push("<li>" + escapeReleaseNotesHTML(rest) + "</li>");
          continue;
        }
      }
      if (firstChar === "#") {
        let hashCount = 0;
        while (hashCount < trimmed.length && trimmed.charAt(hashCount) === "#") {
          hashCount += 1;
        }
        if (hashCount >= 1 && hashCount <= 6) {
          const afterHashes = trimmed.slice(hashCount);
          const spaceRun = afterHashes.match(/^[ \t]+/);
          if (spaceRun) {
            const text = afterHashes.slice(spaceRun[0].length);
            if (text) {
              flushList();
              // Skip the redundant version heading ("# v0.64.1 (2026-04-21)")
              if (!sawVersionHeading && /^v?\d/.test(text)) {
                sawVersionHeading = true;
                continue;
              }
              out.push("<h4>" + escapeReleaseNotesHTML(text) + "</h4>");
              continue;
            }
          }
        }
      }
      flushList();
      out.push("<p>" + escapeReleaseNotesHTML(trimmed) + "</p>");
    }
    flushList();
    return out.join("");
  }

  function setCheckButtonLoading(checkBtn, isLoading) {
    if (!checkBtn) return;
    checkBtn.disabled = isLoading;
    const spinner = checkBtn.querySelector(".btn-spinner");
    if (spinner) {
      spinner.style.display = isLoading ? "inline-block" : "none";
    }
    const label = checkBtn.querySelector(".btn-label");
    if (label) {
      label.textContent = isLoading ? "Checking\u2026" : "Check for updates";
    }
  }

  function syncReleaseNotes(notesText, notesContainer, notesBody, notesVersion, latest) {
    if (!notesContainer) return;
    const html = renderReleaseNotesHTML(notesText);
    notesContainer.hidden = !html;
    if (notesBody) {
      notesBody.innerHTML = html;
    }
    if (notesVersion) {
      notesVersion.textContent = latest ? "\u00b7 v" + String(latest).replace(/^v/, "") : "";
    }
  }

  function syncWhatsNew(notesText, whatsNewBtn, whatsNewBody, updateAvailable) {
    if (whatsNewBody) {
      whatsNewBody.innerHTML = renderReleaseNotesHTML(notesText);
    }
    if (whatsNewBtn) {
      // Only show "What's new" when there's actually a new version — when
      // the device is up-to-date the release notes are still surfaced via
      // the disclosure below, so the modal button would be redundant.
      whatsNewBtn.hidden = !(updateAvailable && notesText);
    }
  }

  function renderVersionCheckResult(elements, data) {
    if (elements.latestEl) {
      elements.latestEl.textContent = data.latest || "\u2014";
    }
    if (elements.updateBtn) {
      elements.updateBtn.disabled = !data.update_available;
    }
    syncReleaseNotes(
      data.release_notes,
      elements.notesContainer,
      elements.notesBody,
      elements.notesVersion,
      data.latest
    );
    syncWhatsNew(
      data.release_notes,
      elements.whatsNewBtn,
      elements.whatsNewBody,
      !!data.update_available
    );
  }

  function appendForceParam(versionUrl) {
    const separator = versionUrl.includes("?") ? "&" : "?";
    return versionUrl + separator + "force=1";
  }

  async function fetchVersionData(versionUrl, { force = false } = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);
    try {
      // Manual "Check for updates" clicks pass ?force=1 so the server
      // bypasses its 1h cache and actually hits GitHub. Silent/background
      // checks leave the cache alone.
      const url = force ? appendForceParam(versionUrl) : versionUrl;
      const response = await fetch(url, {
        cache: "no-store",
        signal: controller.signal,
      });
      const data = await response.json();
      if (
        response.ok &&
        data &&
        typeof data === "object" &&
        "latest" in data
      ) {
        setCachedVersionData(data);
      }
      return data;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  function hydrateVersionCheckFromCache() {
    const data = getCachedVersionData();
    if (!data) return false;
    renderVersionCheckResult(getVersionElements(), data);
    return true;
  }

  function getExportRequestInit(includeKeys) {
    if (!includeKeys) {
      return { cache: "no-store" };
    }
    return {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ include_keys: true }),
      cache: "no-store",
    };
  }

  function setHeaderButtonsDisabled(disabled) {
    for (const btn of document.querySelectorAll(".header-actions .header-button")) {
      btn.disabled = disabled;
    }
  }

  function createActionsModule({ config, state, shared, logs, modals }) {
    const { renderUpdateFailureBanner } = shared;
    const {
      closeRebootConfirm,
      closeRollbackConfirm,
      closeShutdownConfirm,
      closeWhatsNew,
      openRebootConfirm,
      openRollbackConfirm,
      openShutdownConfirm,
      openWhatsNew,
    } = modals;

    async function checkForUpdates(options) {
      const elements = getVersionElements();
      const silent = !!(options && options.silent);
      // Manual clicks force a fresh server-side fetch so a stale 1h cache
      // can't hide a release that actually exists. Silent/background
      // refreshes reuse whatever the server already has.
      const force = !silent;
      setCheckButtonLoading(elements.checkBtn, true);
      try {
        const data = await fetchVersionData(config.versionUrl, { force });
        renderVersionCheckResult(elements, data);
        if (!silent) {
          if (data.update_available) {
            showResponseModal(
              "success",
              `Update available: v${String(data.latest).replace(/^v/, "")}`
            );
          } else if (data.latest) {
            showResponseModal("success", "You're on the latest version.");
          } else {
            // Server produces a complete, self-contained reason in
            // `check_error` (e.g. "Couldn't reach GitHub: timeout" or
            // "Latest GitHub release (...) is not a stable X.Y.Z tag ..."),
            // so show it verbatim instead of prepending a possibly-wrong
            // "couldn't reach GitHub" preamble.
            const message = data.check_error
              ? data.check_error
              : "Unable to check for updates. Try again later.";
            showResponseModal("failure", message);
          }
        }
      } catch (e) {
        if (e?.name === "AbortError") {
          return;
        }
        console.warn("Version check failed:", e);
        if (!silent) {
          showResponseModal(
            "failure",
            "Unable to check for updates. Try again later."
          );
        }
      } finally {
        setCheckButtonLoading(elements.checkBtn, false);
      }
    }

    async function refreshUpdateStatus() {
      try {
        const resp = await fetch(config.updateStatusUrl, { cache: "no-store" });
        if (!resp.ok) return;
        const data = await resp.json();
        renderUpdateFailureBanner(
          data?.last_failure ?? null,
          data?.prev_version ?? null
        );
      } catch (e) {
        console.warn("Update status refresh failed:", e);
      }
    }

    function pollUpdateStatusUntilDone(logLabel) {
      if (state.updateTimer) clearInterval(state.updateTimer);
      state.updateTimer = setInterval(async () => {
        try {
          await logs.fetchAndRenderLogs();
          const sresp = await fetch(config.updateStatusUrl);
          const sdata = await sresp.json();
          renderUpdateFailureBanner(
            sdata?.last_failure ?? null,
            sdata?.prev_version ?? null
          );
          if (!sdata?.running) {
            clearInterval(state.updateTimer);
            state.updateTimer = null;
            setTimeout(logs.fetchAndRenderLogs, 500);
            // Silent refresh — the user was just watching the update log
            // stream, they don't need another toast announcing the state.
            checkForUpdates({ silent: true });
          }
        } catch (e) {
          console.warn(`${logLabel} status poll failed:`, e);
          clearInterval(state.updateTimer);
          state.updateTimer = null;
        }
      }, 2000);
    }

    async function runUpdateAction({
      url,
      kind,
      startingLabel,
      failureMessage,
    }) {
      if (!url) {
        showResponseModal("failure", `${kind} is not available on this build.`);
        return;
      }
      try {
        setHeaderButtonsDisabled(true);
        const resp = await fetch(url, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showResponseModal("failure", data.error || failureMessage);
          return;
        }
        showResponseModal("success", data.message || startingLabel);
        pollUpdateStatusUntilDone(kind);
      } catch (e) {
        console.warn(`Failed to start ${kind.toLowerCase()}:`, e);
        showResponseModal("failure", failureMessage);
      } finally {
        setHeaderButtonsDisabled(false);
      }
    }

    async function startUpdate() {
      await runUpdateAction({
        url: config.startUpdateUrl,
        kind: "Update",
        startingLabel: "Update started.",
        failureMessage: "Failed to start update",
      });
    }

    async function startRollback() {
      closeRollbackConfirm();
      await runUpdateAction({
        url: config.rollbackUpdateUrl,
        kind: "Rollback",
        startingLabel: "Rollback started.",
        failureMessage: "Failed to start rollback",
      });
    }

    async function exportConfig() {
      const btn = document.getElementById("exportConfigBtn");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Downloading…";
      }
      const include = document.getElementById("includeKeys")?.checked;
      try {
        const resp = await fetch(
          config.exportSettingsUrl,
          getExportRequestInit(include)
        );
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showResponseModal("failure", "Export failed");
          return;
        }
        const blob = new Blob([JSON.stringify(data.data, null, 2)], {
          type: "application/json",
        });
        const anchor = document.createElement("a");
        anchor.href = URL.createObjectURL(blob);
        anchor.download = `inkypi_backup_${Date.now()}.json`;
        anchor.click();
        URL.revokeObjectURL(anchor.href);
        showResponseModal("success", "Backup downloaded");
      } catch (e) {
        console.error("Export failed", e);
        showResponseModal("failure", "Export failed");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Download Backup";
        }
      }
    }

    async function importConfig() {
      const btn = document.getElementById("importConfigBtn");
      const fileInput = document.getElementById("importFile");
      const file = fileInput?.files?.[0];
      if (!file) {
        showResponseModal("failure", "Choose a backup file first");
        return;
      }
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Restoring…";
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
          btn.textContent = "Restore from file";
          btn.disabled = !fileInput?.files?.length;
        }
      }
    }

    async function handleShutdown(reboot) {
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
        console.debug("Shutdown request ended early while the device was shutting down:", e);
      }
    }

    function stop() {
      if (state.updateTimer) {
        clearInterval(state.updateTimer);
        state.updateTimer = null;
      }
    }

    function bind() {
      document
        .getElementById("exportConfigBtn")
        ?.addEventListener("click", exportConfig);
      document
        .getElementById("importConfigBtn")
        ?.addEventListener("click", importConfig);
      const importFileInput = document.getElementById("importFile");
      const importBtn = document.getElementById("importConfigBtn");
      const importFileName = document.getElementById("importFileName");
      if (importFileInput && importBtn) {
        importFileInput.addEventListener("change", () => {
          importBtn.disabled = !importFileInput.files?.length;
          if (importFileName) {
            const file = importFileInput.files?.[0];
            importFileName.textContent = file ? file.name : "No file chosen";
          }
        });
      }

      document
        .getElementById("checkUpdatesBtn")
        ?.addEventListener("click", checkForUpdates);
      document
        .getElementById("startUpdateBtn")
        ?.addEventListener("click", startUpdate);
      document.getElementById("whatsNewBtn")?.addEventListener("click", openWhatsNew);
      document
        .getElementById("closeWhatsNewModalBtn")
        ?.addEventListener("click", closeWhatsNew);

      document.getElementById("rebootBtn")?.addEventListener("click", openRebootConfirm);
      document
        .getElementById("shutdownBtn")
        ?.addEventListener("click", openShutdownConfirm);
      document
        .getElementById("confirmRebootBtn")
        ?.addEventListener("click", () => handleShutdown(true));
      document
        .getElementById("cancelRebootBtn")
        ?.addEventListener("click", closeRebootConfirm);
      document
        .getElementById("closeRebootConfirmModalBtn")
        ?.addEventListener("click", closeRebootConfirm);
      document
        .getElementById("confirmShutdownBtn")
        ?.addEventListener("click", () => handleShutdown(false));
      document
        .getElementById("cancelShutdownBtn")
        ?.addEventListener("click", closeShutdownConfirm);
      document
        .getElementById("closeShutdownConfirmModalBtn")
        ?.addEventListener("click", closeShutdownConfirm);
      document
        .getElementById("rollbackUpdateBtn")
        ?.addEventListener("click", openRollbackConfirm);
      document
        .getElementById("confirmRollbackBtn")
        ?.addEventListener("click", startRollback);
      document
        .getElementById("cancelRollbackBtn")
        ?.addEventListener("click", closeRollbackConfirm);
      document
        .getElementById("closeRollbackConfirmModalBtn")
        ?.addEventListener("click", closeRollbackConfirm);
    }

    return {
      bind,
      checkForUpdates,
      exportConfig,
      handleShutdown,
      hydrateVersionCheckFromCache,
      importConfig,
      refreshUpdateStatus,
      startRollback,
      startUpdate,
      stop,
    };
  }

  settingsModules.createActionsModule = createActionsModule;
  settingsModules.renderReleaseNotesHTML = renderReleaseNotesHTML;
  settingsModules.renderVersionCheckResult = renderVersionCheckResult;
})();

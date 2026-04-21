(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function getVersionElements() {
    return {
      badge: document.getElementById("updateBadge"),
      checkBtn: document.getElementById("checkUpdatesBtn"),
      latestEl: document.getElementById("latestVersion"),
      notesBody: document.getElementById("releaseNotesBody"),
      notesContainer: document.getElementById("releaseNotesContainer"),
      updateBtn: document.getElementById("startUpdateBtn"),
      whatsNewBody: document.getElementById("whatsNewBody"),
      whatsNewBtn: document.getElementById("whatsNewBtn"),
    };
  }

  function setStatusChip(chip, text, variant) {
    if (!chip) return;
    chip.textContent = text;
    chip.className = variant ? `status-chip ${variant}` : "status-chip";
  }

  function setCheckButtonLoading(checkBtn, isLoading) {
    if (!checkBtn) return;
    checkBtn.disabled = isLoading;
    const spinner = checkBtn.querySelector(".btn-spinner");
    if (spinner) {
      spinner.style.display = isLoading ? "inline-block" : "none";
    }
  }

  function syncReleaseNotes(notesText, notesContainer, notesBody) {
    if (!notesContainer) return;
    notesContainer.hidden = !notesText;
    if (notesBody) {
      notesBody.textContent = notesText || "";
    }
  }

  function syncWhatsNew(notesText, whatsNewBtn, whatsNewBody) {
    if (whatsNewBody) {
      whatsNewBody.textContent = notesText || "";
    }
    if (whatsNewBtn) {
      whatsNewBtn.hidden = !notesText;
    }
  }

  function renderVersionCheckResult(elements, data) {
    if (elements.latestEl) {
      elements.latestEl.textContent = data.latest || "—";
    }
    if (data.update_available) {
      setStatusChip(elements.badge, "Update available", "warning");
      if (elements.updateBtn) elements.updateBtn.disabled = false;
    } else if (data.latest) {
      setStatusChip(elements.badge, "Up to date", "success");
      if (elements.updateBtn) elements.updateBtn.disabled = true;
    } else {
      setStatusChip(elements.badge, "Unable to check");
    }
    syncReleaseNotes(
      data.release_notes,
      elements.notesContainer,
      elements.notesBody
    );
    syncWhatsNew(data.release_notes, elements.whatsNewBtn, elements.whatsNewBody);
  }

  async function fetchVersionData(versionUrl) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(versionUrl, {
        cache: "no-store",
        signal: controller.signal,
      });
      return await response.json();
    } finally {
      clearTimeout(timeoutId);
    }
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

    async function checkForUpdates() {
      const elements = getVersionElements();
      setCheckButtonLoading(elements.checkBtn, true);
      setStatusChip(elements.badge, "Checking...");
      try {
        const data = await fetchVersionData(config.versionUrl);
        renderVersionCheckResult(elements, data);
      } catch (e) {
        if (e?.name === "AbortError") {
          console.debug("Version check aborted:", e);
          return;
        }
        console.warn("Version check failed:", e);
        setStatusChip(elements.badge, "Check failed");
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
            checkForUpdates();
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
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Restoring…";
      }
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
      if (importFileInput && importBtn) {
        importFileInput.addEventListener("change", () => {
          importBtn.disabled = !importFileInput.files?.length;
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
      importConfig,
      refreshUpdateStatus,
      startRollback,
      startUpdate,
      stop,
    };
  }

  settingsModules.createActionsModule = createActionsModule;
})();

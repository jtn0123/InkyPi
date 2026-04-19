(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

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
      const badge = document.getElementById("updateBadge");
      const latestEl = document.getElementById("latestVersion");
      const updateBtn = document.getElementById("startUpdateBtn");
      const checkBtn = document.getElementById("checkUpdatesBtn");
      const notesContainer = document.getElementById("releaseNotesContainer");
      const notesBody = document.getElementById("releaseNotesBody");
      const whatsNewBtn = document.getElementById("whatsNewBtn");
      const whatsNewBody = document.getElementById("whatsNewBody");

      if (checkBtn) {
        checkBtn.disabled = true;
        const sp = checkBtn.querySelector(".btn-spinner");
        if (sp) sp.style.display = "inline-block";
      }
      if (badge) {
        badge.textContent = "Checking...";
        badge.className = "status-chip";
      }
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000);
        const resp = await fetch(config.versionUrl, {
          cache: "no-store",
          signal: controller.signal,
        });
        clearTimeout(timeoutId);
        const data = await resp.json();
        if (latestEl) latestEl.textContent = data.latest || "\u2014";
        if (data.update_available) {
          if (badge) {
            badge.textContent = "Update available";
            badge.className = "status-chip warning";
          }
          if (updateBtn) updateBtn.disabled = false;
        } else if (data.latest) {
          if (badge) {
            badge.textContent = "Up to date";
            badge.className = "status-chip success";
          }
          if (updateBtn) updateBtn.disabled = true;
        } else if (badge) {
          badge.textContent = "Unable to check";
          badge.className = "status-chip";
        }
        if (data.release_notes && notesContainer && notesBody) {
          notesBody.textContent = data.release_notes;
          notesContainer.hidden = false;
        } else if (notesContainer) {
          notesContainer.hidden = true;
        }
        if (data.release_notes && whatsNewBtn && whatsNewBody) {
          whatsNewBody.textContent = data.release_notes;
          whatsNewBtn.hidden = false;
        } else if (whatsNewBtn) {
          whatsNewBtn.hidden = true;
        }
      } catch (e) {
        if (e?.name === "AbortError") {
          console.debug("Version check aborted:", e);
          return;
        } else {
          console.warn("Version check failed:", e);
        }
        if (badge) {
          badge.textContent = "Check failed";
          badge.className = "status-chip";
        }
      } finally {
        if (checkBtn) {
          checkBtn.disabled = false;
          const sp = checkBtn.querySelector(".btn-spinner");
          if (sp) sp.style.display = "none";
        }
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
      const btns = document.querySelectorAll(".header-actions .header-button");
      try {
        for (const btn of btns) {
          btn.disabled = true;
        }
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
        for (const btn of btns) {
          btn.disabled = false;
        }
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
        btn.textContent = "Downloading\u2026";
      }
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
        btn.textContent = "Restoring\u2026";
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
        // Expected — device is shutting down, connection will be severed
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
      document.getElementById("startUpdateBtn")?.addEventListener("click", startUpdate);
      document
        .getElementById("whatsNewBtn")
        ?.addEventListener("click", openWhatsNew);
      document
        .getElementById("closeWhatsNewModalBtn")
        ?.addEventListener("click", closeWhatsNew);

      document
        .getElementById("rebootBtn")
        ?.addEventListener("click", openRebootConfirm);
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

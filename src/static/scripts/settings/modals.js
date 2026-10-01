(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function syncModalOpenState(ui) {
    if (ui?.syncModalOpenState) {
      ui.syncModalOpenState();
      return;
    }
    const anyOpen = document.querySelector(".modal.is-open");
    document.body.classList.toggle("modal-open", !!anyOpen);
  }

  function isDeviceActionModalOpen(modalId) {
    const modal = document.getElementById(modalId);
    return !!(modal && !modal.hidden);
  }

  function createModalModule({ ui }) {
    let lastWhatsNewTrigger = null;

    function setDeviceActionModalOpen(modalId, open, triggerEl) {
      const modal = document.getElementById(modalId);
      if (!modal) return;
      modal.hidden = !open;
      modal.style.display = open ? "flex" : "none";
      modal.classList.toggle("is-open", !!open);
      syncModalOpenState(ui);
      if (open) {
        globalThis.InkyPiModalFocus.activate(modal, triggerEl, () => setDeviceActionModalOpen(modalId, false));
        return;
      }
      globalThis.InkyPiModalFocus.deactivate(modal);

    }

    function openRebootConfirm(event) {
      setDeviceActionModalOpen("rebootConfirmModal", true, event?.currentTarget);
    }

    function closeRebootConfirm() {
      setDeviceActionModalOpen("rebootConfirmModal", false);
    }

    function openShutdownConfirm(event) {
      setDeviceActionModalOpen(
        "shutdownConfirmModal",
        true,
        event?.currentTarget
      );
    }

    function closeShutdownConfirm() {
      setDeviceActionModalOpen("shutdownConfirmModal", false);
    }

    function openRollbackConfirm(event) {
      const btn = document.getElementById("rollbackUpdateBtn");
      const target = btn?.dataset?.prevVersion || "the previous version";
      const confirmVersion = document.getElementById("rollbackConfirmVersion");
      if (confirmVersion) confirmVersion.textContent = target;
      setDeviceActionModalOpen(
        "rollbackConfirmModal",
        true,
        event?.currentTarget
      );
    }

    function closeRollbackConfirm() {
      setDeviceActionModalOpen("rollbackConfirmModal", false);
    }

    function openWhatsNew(event) {
      const modal = document.getElementById("whatsNewModal");
      if (!modal) return;
      lastWhatsNewTrigger = event?.currentTarget || null;
      modal.hidden = false;
      modal.style.display = "flex";
      modal.classList.add("is-open");
      syncModalOpenState(ui);
      globalThis.InkyPiModalFocus.activate(modal, lastWhatsNewTrigger, closeWhatsNew);
    }

    function closeWhatsNew() {
      const modal = document.getElementById("whatsNewModal");
      if (!modal) return;
      modal.hidden = true;
      modal.style.display = "none";
      modal.classList.remove("is-open");
      globalThis.InkyPiModalFocus.deactivate(modal);
      syncModalOpenState(ui);

    }

    function bindGlobalDismissals() {
      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        const whatsNewModal = document.getElementById("whatsNewModal");
        if (whatsNewModal && !whatsNewModal.hidden) {
          event.preventDefault();
          closeWhatsNew();
        } else if (isDeviceActionModalOpen("rebootConfirmModal")) {
          event.preventDefault();
          closeRebootConfirm();
        } else if (isDeviceActionModalOpen("shutdownConfirmModal")) {
          event.preventDefault();
          closeShutdownConfirm();
        } else if (isDeviceActionModalOpen("rollbackConfirmModal")) {
          event.preventDefault();
          closeRollbackConfirm();
        }
      });

      globalThis.addEventListener("click", (event) => {
        const whatsNewModal = document.getElementById("whatsNewModal");
        const rebootModal = document.getElementById("rebootConfirmModal");
        const shutdownModal = document.getElementById("shutdownConfirmModal");
        const rollbackModal = document.getElementById("rollbackConfirmModal");
        if (event.target === whatsNewModal) closeWhatsNew();
        else if (event.target === rebootModal) closeRebootConfirm();
        else if (event.target === shutdownModal) closeShutdownConfirm();
        else if (event.target === rollbackModal) closeRollbackConfirm();
      });
    }

    return {
      bindGlobalDismissals,
      closeRebootConfirm,
      closeRollbackConfirm,
      closeShutdownConfirm,
      closeWhatsNew,
      isDeviceActionModalOpen,
      openRebootConfirm,
      openRollbackConfirm,
      openShutdownConfirm,
      openWhatsNew,
      setDeviceActionModalOpen,
    };
  }

  settingsModules.createModalModule = createModalModule;
})();

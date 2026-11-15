(function (global) {
  global.InkyPiPlaylist = global.InkyPiPlaylist || {};
  const ns = global.InkyPiPlaylist;

  function syncModalOpenState() {
    const ui = global.InkyPiUI;
    const delegatedState =
      typeof ui?.syncModalOpenState === "function"
        ? ui.syncModalOpenState()
        : null;
    const open =
      typeof delegatedState === "boolean"
        ? delegatedState
        : document.querySelector(".modal.is-open, .thumbnail-preview-modal.is-open");
    if (typeof ui?.syncModalOpenState !== "function")
      document.body.classList.toggle("modal-open", !!open);
  }

  // The shared InkyPiModalFocus helper makes the page behind an open dialog
  // inert, moves focus in, keeps Tab inside, closes the dialog on Escape and
  // hands focus back to whatever opened it.
  function trapFocus(modal, triggerEl, modalId) {
    global.InkyPiModalFocus?.activate(modal, triggerEl, () =>
      closeModalById(modalId)
    );
  }

  function releaseFocus(modal) {
    global.InkyPiModalFocus?.deactivate(modal);
  }

  function syncMobileTimeInputs() {
    const mobile = global.matchMedia?.("(max-width: 640px)")?.matches;
    ["start_time", "end_time"].forEach((id) => {
      const input = document.getElementById(id);
      if (!input) return;
      input.type = mobile ? "text" : "time";
      if (mobile) {
        input.inputMode = "numeric";
        input.pattern = "([01][0-9]|2[0-3]):[0-5][0-9]";
        input.placeholder = "HH:MM";
      } else {
        input.removeAttribute("inputmode");
        input.removeAttribute("pattern");
        input.removeAttribute("placeholder");
      }
    });
  }

  function setModalOpen(modalId, open, triggerEl) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modal.hidden = !open;
    modal.style.display = open ? "flex" : "none";
    modal.classList.toggle("is-open", open);
    syncModalOpenState();
    if (open) {
      trapFocus(modal, triggerEl, modalId);
      return;
    }
    releaseFocus(modal);
  }

  function closeModalById(modalId) {
    switch (modalId) {
      case "deleteInstanceModal":
        ns.closeDeleteInstanceModal();
        return;
      case "deletePlaylistModal":
        ns.closeDeletePlaylistModal();
        return;
      case "displayNextConfirmModal":
        ns.closeDisplayNextConfirmModal();
        return;
      case "thumbnailPreviewModal":
        ns.closeThumbnailPreview();
        return;
      case "refreshSettingsModal":
        ns.closeRefreshModal();
        return;
      case "playlistModal":
        ns.closeModal();
        return;
      default:
        return;
    }
  }

  function showThumbnailPreview(
    pluginId,
    pluginName,
    instanceName,
    instanceLabel,
    triggerEl
  ) {
    const img = document.getElementById("thumbnailPreviewImage");
    const info = document.getElementById("thumbnailPreviewInfo");
    if (!img || !info) return;
    // Same URL the thumbnail itself loads (plugin.plugin_instance_image).
    // Instances are keyed by plugin and name, not by playlist.
    img.src = `/instance_image/${encodeURIComponent(
      pluginId
    )}/${encodeURIComponent(instanceName)}`;
    const label = instanceLabel || instanceName;
    if (label && label !== pluginName) {
      info.textContent = `Plugin: ${pluginName} | Instance: ${label}`;
    } else {
      info.textContent = `Plugin: ${pluginName}`;
    }
    // Focus goes back to the thumbnail that opened it, even after a mouse
    // click (which doesn't focus a button in every browser).
    setModalOpen("thumbnailPreviewModal", true, triggerEl);
  }

  function closeThumbnailPreview() {
    setModalOpen("thumbnailPreviewModal", false);
  }

  function openRefreshModal(
    playlistName,
    pluginId,
    instanceName,
    refreshSettings,
    triggerEl
  ) {
    ns.state.currentEditPlaylist = playlistName;
    ns.state.currentEditPluginId = pluginId;
    ns.state.currentEditInstance = instanceName;
    if (
      !ns.runtime.playlistRefreshManager &&
      typeof global.createRefreshSettingsManager === "function"
    ) {
      ns.runtime.playlistRefreshManager = global.createRefreshSettingsManager(
        "refreshSettingsModal",
        "modal"
      );
    }
    if (ns.runtime.playlistRefreshManager) {
      ns.runtime.playlistRefreshManager.open({ refreshSettings });
      const modal = document.getElementById("refreshSettingsModal");
      if (modal) {
        modal.hidden = false;
        modal.classList.add("is-open");
        syncModalOpenState();
        trapFocus(modal, triggerEl, "refreshSettingsModal");
      }
      return;
    }
    setModalOpen("refreshSettingsModal", true, triggerEl);
  }

  function closeRefreshModal() {
    if (ns.runtime.playlistRefreshManager) {
      ns.runtime.playlistRefreshManager.close();
      const modal = document.getElementById("refreshSettingsModal");
      if (modal) {
        modal.hidden = true;
        modal.classList.remove("is-open");
        syncModalOpenState();
        releaseFocus(modal);
      }
      return;
    }
    setModalOpen("refreshSettingsModal", false);
  }

  function openCreateModal(triggerEl) {
    const modal = document.getElementById("playlistModal");
    syncMobileTimeInputs();
    document.getElementById("modalTitle").textContent = "New Playlist";
    document.getElementById("playlist_name").value = "";
    document.getElementById("editingPlaylistName").value = "";
    document.getElementById("start_time").value = "09:00";
    document.getElementById("end_time").value = "17:00";
    const cycleInput = document.getElementById("cycle_minutes");
    if (cycleInput) cycleInput.value = "";
    if (modal) {
      modal.dataset.mode = "create";
      delete modal.dataset.originalEndTime;
    }
    document.getElementById("deleteButton").classList.add("hidden");
    setModalOpen("playlistModal", true, triggerEl);
  }

  function openEditModal(
    playlistName,
    startTime,
    endTime,
    cycleMinutes,
    triggerEl
  ) {
    const modal = document.getElementById("playlistModal");
    syncMobileTimeInputs();
    document.getElementById("modalTitle").textContent = "Update Playlist";
    document.getElementById("playlist_name").value = playlistName;
    document.getElementById("editingPlaylistName").value = playlistName;
    document.getElementById("start_time").value =
      ns.normaliseTimeForInput(startTime);
    document.getElementById("end_time").value = ns.normaliseTimeForInput(endTime);
    const cycleInput = document.getElementById("cycle_minutes");
    if (cycleInput) cycleInput.value = cycleMinutes || "";
    if (modal) {
      modal.dataset.mode = "edit";
      modal.dataset.originalEndTime = endTime || "";
    }
    document.getElementById("deleteButton").classList.remove("hidden");
    setModalOpen("playlistModal", true, triggerEl);
  }

  function openModal() {
    setModalOpen("playlistModal", true);
  }

  function closeModal() {
    setModalOpen("playlistModal", false);
  }

  function openDeletePlaylistModal(name, triggerEl) {
    const el = document.getElementById("deletePlaylistModal");
    const txt = document.getElementById("deletePlaylistText");
    const btn = document.getElementById("confirmDeletePlaylistBtn");
    if (!el || !txt || !btn) return;
    txt.textContent = `Delete playlist '${name}'?`;
    setModalOpen("deletePlaylistModal", true, triggerEl);
    btn.onclick = () =>
      runConfirmed(btn, "cancelDeletePlaylistBtn", async () => {
        try {
          const resp = await fetch(
            ns.config.delete_playlist_base_url + encodeURIComponent(name),
            { method: "DELETE" }
          );
          const result = await handleJsonResponse(resp);
          if (resp.ok && result?.success) {
            location.reload();
            return true;
          }
        } catch (error) {
          console.debug("Failed to delete playlist from modal:", error);
          showResponseModal("failure", "Failed to delete playlist");
        }
        return false;
      });
  }

  // Run a confirm dialog's request with its buttons locked, so a double
  // click sends one request. *request* resolves true when the page is
  // reloading; otherwise the buttons unlock so the user can retry or cancel.
  async function runConfirmed(confirmBtn, cancelBtnId, request) {
    if (confirmBtn.disabled) return;
    const cancelBtn = document.getElementById(cancelBtnId);
    const setLocked = (locked) => {
      confirmBtn.disabled = locked;
      confirmBtn.setAttribute("aria-busy", String(locked));
      if (cancelBtn) cancelBtn.disabled = locked;
    };
    setLocked(true);
    let reloading = false;
    try {
      reloading = await request();
    } finally {
      if (!reloading) setLocked(false);
    }
  }

  function closeDeletePlaylistModal() {
    setModalOpen("deletePlaylistModal", false);
  }

  function openDeleteInstanceModal(
    playlistName,
    pluginId,
    instanceName,
    triggerEl,
    instanceLabel
  ) {
    const el = document.getElementById("deleteInstanceModal");
    const txt = document.getElementById("deleteInstanceText");
    const btn = document.getElementById("confirmDeleteInstanceBtn");
    if (!el || !txt || !btn) return;
    const label = instanceLabel || instanceName;
    txt.textContent = `Delete instance '${label}'?`;
    setModalOpen("deleteInstanceModal", true, triggerEl);
    btn.onclick = () =>
      runConfirmed(btn, "cancelDeleteInstanceBtn", async () => {
        try {
          const resp = await fetch(ns.config.delete_plugin_instance_url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              playlist_name: playlistName,
              plugin_id: pluginId,
              plugin_instance: instanceName,
            }),
          });
          const result = await handleJsonResponse(resp);
          if (resp.ok && result?.success) {
            location.reload();
            return true;
          }
        } catch (error) {
          console.debug("Failed to delete playlist instance from modal:", error);
          showResponseModal("failure", "Failed to delete instance");
        }
        return false;
      });
  }

  function closeDeleteInstanceModal() {
    setModalOpen("deleteInstanceModal", false);
  }

  function openDisplayNextConfirmModal(name, triggerEl) {
    const el = document.getElementById("displayNextConfirmModal");
    const txt = document.getElementById("displayNextConfirmText");
    const btn = document.getElementById("confirmDisplayNextBtn");
    if (!el || !txt || !btn) {
      ns.displayNextInPlaylist(name);
      return;
    }
    txt.textContent = `Advance '${name}' to the next plugin now?`;
    setModalOpen("displayNextConfirmModal", true, triggerEl);
    btn.onclick = async function () {
      ns.closeDisplayNextConfirmModal();
      await ns.displayNextInPlaylist(name);
    };
  }

  function closeDisplayNextConfirmModal() {
    setModalOpen("displayNextConfirmModal", false);
  }

  function initModalLifecycle() {
    if (ns.runtime.modalLifecycleBound) return;
    document
      .getElementById("closePlaylistModalBtn")
      ?.addEventListener("click", closeModal);
    document
      .getElementById("closeRefreshModalBtn")
      ?.addEventListener("click", closeRefreshModal);
    document
      .getElementById("closeThumbnailPreviewBtn")
      ?.addEventListener("click", closeThumbnailPreview);
    document
      .getElementById("cancelDeletePlaylistBtn")
      ?.addEventListener("click", closeDeletePlaylistModal);
    document
      .getElementById("cancelDeleteInstanceBtn")
      ?.addEventListener("click", closeDeleteInstanceModal);
    document
      .getElementById("cancelDisplayNextBtn")
      ?.addEventListener("click", closeDisplayNextConfirmModal);

    global.addEventListener("click", (event) => {
      if (event.target?.id === "playlistModal") closeModal();
      if (event.target?.id === "refreshSettingsModal") closeRefreshModal();
      if (event.target?.id === "thumbnailPreviewModal") closeThumbnailPreview();
      if (event.target?.id === "deletePlaylistModal") closeDeletePlaylistModal();
      if (event.target?.id === "deleteInstanceModal") closeDeleteInstanceModal();
      if (event.target?.id === "displayNextConfirmModal") {
        closeDisplayNextConfirmModal();
      }
    });
    ns.runtime.modalLifecycleBound = true;
  }

  Object.assign(ns, {
    closeDeleteInstanceModal,
    closeDeletePlaylistModal,
    closeDisplayNextConfirmModal,
    closeModal,
    closeModalById,
    closeRefreshModal,
    closeThumbnailPreview,
    initModalLifecycle,
    openCreateModal,
    openDeleteInstanceModal,
    openDeletePlaylistModal,
    openDisplayNextConfirmModal,
    openEditModal,
    openModal,
    openRefreshModal,
    setModalOpen,
    showThumbnailPreview,
    syncModalOpenState,
  });
})(globalThis);

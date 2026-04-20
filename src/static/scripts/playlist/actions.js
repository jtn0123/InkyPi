(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

  function getActionPayload(actionButton) {
    const { dataset } = actionButton;
    return {
      cycleMinutes: dataset.cycleMinutes,
      endTime: dataset.endTime,
      instance: dataset.instance,
      instanceLabel: dataset.instanceLabel || dataset.instance,
      playlist: dataset.playlist,
      playlistName: dataset.playlistName,
      pluginId: dataset.pluginId,
      // Reads the data-refresh payload from the delegated button.
      refresh: dataset.refresh,
      startTime: dataset.startTime,
    };
  }

  function handlePlaylistActionClick(event) {
    const actionButton = event.target.closest("[data-playlist-action]");
    if (
      !actionButton ||
      actionButton.disabled ||
      actionButton.getAttribute("aria-disabled") === "true"
    ) {
      return false;
    }

    const action = actionButton.dataset.playlistAction;
    const payload = getActionPayload(actionButton);
    if (action === "toggle-card") {
      ns.togglePlaylistCard(actionButton);
      return true;
    }
    if (action === "edit-playlist") {
      ns.openEditModal(
        payload.playlistName,
        payload.startTime,
        payload.endTime,
        payload.cycleMinutes,
        actionButton
      );
      return true;
    }
    if (action === "confirm-display-next") {
      ns.openDisplayNextConfirmModal(payload.playlist, actionButton);
      return true;
    }
    if (action === "delete-playlist") {
      ns.openDeletePlaylistModal(payload.playlist, actionButton);
      return true;
    }
    if (action === "delete-instance") {
      ns.openDeleteInstanceModal(
        payload.playlist,
        payload.pluginId,
        payload.instance,
        actionButton,
        payload.instanceLabel
      );
      return true;
    }
    if (action === "edit-refresh") {
      ns.openRefreshModal(
        payload.playlist,
        payload.pluginId,
        payload.instance,
        ns.parseRefreshSettings(payload.refresh),
        actionButton
      );
      return true;
    }
    if (action === "display-instance") {
      ns.displayPluginInstance(
        payload.playlist,
        payload.pluginId,
        payload.instance,
        actionButton
      );
      return true;
    }
    return false;
  }

  async function saveRefreshSettings() {
    if (!ns.runtime.playlistRefreshManager) return;
    await ns.runtime.playlistRefreshManager.submit(async (formData) => {
      const data = new FormData();
      data.append("plugin_id", ns.state.currentEditPluginId);
      data.append("refresh_settings", JSON.stringify(formData));
      const encodedInstance = encodeURIComponent(ns.state.currentEditInstance);
      const response = await fetch(
        ns.config.update_instance_base_url + encodedInstance,
        {
          method: "PUT",
          body: data,
        }
      );
      const result = await response.json();
      if (response.ok) {
        sessionStorage.setItem(
          "storedMessage",
          JSON.stringify({ type: "success", text: `Success! ${result.message}` })
        );
        location.reload();
        return;
      }
      throw new Error(result.error || "Failed to update refresh settings");
    });
  }

  async function deletePluginInstance(playlistName, pluginId, pluginInstance) {
    try {
      const response = await fetch(ns.config.delete_plugin_instance_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          playlist_name: playlistName,
          plugin_id: pluginId,
          plugin_instance: pluginInstance,
        }),
      });
      const result = await handleJsonResponse(response);
      if (response.ok && result?.success) {
        location.reload();
      }
    } catch (error) {
      console.error("Error:", error);
      showResponseModal(
        "failure",
        "An error occurred while processing your request."
      );
    }
  }

  async function displayNextInPlaylist(name) {
    const card = document.querySelector(
      `[data-playlist-name="${CSS.escape(name)}"]`
    );
    if (card && !card.querySelectorAll(".plugin-item").length) {
      showResponseModal(
        "failure",
        "Cannot display next — playlist has no items."
      );
      return;
    }
    try {
      const resp = await fetch(ns.config.display_next_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ playlist_name: name }),
      });
      const result = await handleJsonResponse(resp);
      if (resp.ok && result?.success) {
        showResponseModal("success", "Display updated — refreshing…");
        setTimeout(() => {
          location.reload();
        }, 500);
      }
    } catch (error) {
      console.debug("Failed to trigger display next:", error);
      showResponseModal("failure", "Failed to trigger display");
    }
  }

  function initActionDelegation() {
    if (ns.runtime.actionDelegationBound) return;
    const pageContent = document.getElementById("playlist-page-content");
    if (!pageContent) return;
    pageContent.addEventListener("click", handlePlaylistActionClick);
    ns.runtime.actionDelegationBound = true;
  }

  Object.assign(ns, {
    deletePluginInstance,
    displayNextInPlaylist,
    handlePlaylistActionClick,
    initActionDelegation,
    saveRefreshSettings,
  });
})(globalThis);

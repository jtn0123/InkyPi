(function (global) {
  global.InkyPiPlaylist = global.InkyPiPlaylist || {};
  const ns = global.InkyPiPlaylist;

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
      // A failure rejects, and the manager shows it.
      const result = await fetchJson(
        ns.config.update_instance_base_url + encodedInstance,
        {
          method: "PUT",
          body: data,
        }
      );
      ns.reloadWithMessage("success", `Success! ${result.message}`);
    });
  }

  // Draws the playlist's next item. The request returns once the panel has
  // been drawn, which can take a while on a Pi Zero; the confirm dialog's
  // button shows that it is working (see openDisplayNextConfirmModal).
  // Resolves true when the page is reloading, false when it stays.
  async function displayNextInPlaylist(name) {
    const card = document.querySelector(
      `[data-playlist-name="${CSS.escape(name)}"]`
    );
    if (card && !card.querySelectorAll(".plugin-item").length) {
      showResponseModal(
        "failure",
        "Cannot display next — playlist has no items."
      );
      return false;
    }
    try {
      const result = await fetchJson(ns.config.display_next_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ playlist_name: name }),
      });
      ns.reloadWithMessage("success", result?.message || "Display updated.");
      return true;
    } catch (error) {
      // Shown in the toast below, so it isn't logged as an error.
      console.debug("Failed to trigger display next:", error);
      showResponseModal(
        "failure",
        `Failed to display next: ${globalThis.InkyPiHttp.errorMessage(error)}`
      );
      return false;
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
    displayNextInPlaylist,
    handlePlaylistActionClick,
    initActionDelegation,
    saveRefreshSettings,
  });
})(globalThis);

/* "Display now" on a playlist row, and the toast that outlives the reload after it. */
(function (global) {
  global.InkyPiPlaylist = global.InkyPiPlaylist || {};
  const ns = global.InkyPiPlaylist;

  function restoreStoredMessage() {
    const storedMessage = sessionStorage.getItem("storedMessage");
    if (!storedMessage) return;
    try {
      const { type, text } = JSON.parse(storedMessage);
      showResponseModal(type, text);
    } catch (error) {
      console.debug("Invalid playlist stored message payload:", error);
    }
    sessionStorage.removeItem("storedMessage");
  }

  function bindStoredMessageHandler() {
    if (ns.runtime.storedMessageBound) return;
    ns.runtime.storedMessageBound = true;
    if (document.readyState === "complete") {
      restoreStoredMessage();
      return;
    }
    global.addEventListener("load", restoreStoredMessage, { once: true });
  }

  // The row is found from the button that was pressed, not by id: row ids are
  // instance names, and two playlists can each hold an instance of that name.
  function setRowBusy(btnEl, busy) {
    const row = btnEl?.closest(".plugin-item");
    const spinner = row?.querySelector(".loading-indicator");
    if (spinner) spinner.style.display = busy ? "block" : "none";
    if (row) {
      if (busy) row.setAttribute("aria-busy", "true");
      else row.removeAttribute("aria-busy");
    }
    if (btnEl) btnEl.disabled = busy;
  }

  // The request returns once the panel has been drawn, which can take a while
  // on a Pi Zero; the row spins until then. Success reloads the page, so the
  // row's "Refreshed" time and Playing badge come from the server, and the
  // toast is carried across the reload in sessionStorage.
  async function displayPluginInstance(
    playlistName,
    pluginId,
    pluginInstance,
    btnEl
  ) {
    setRowBusy(btnEl, true);
    try {
      const result = await fetchJson(ns.config.display_plugin_instance_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          playlist_name: playlistName,
          plugin_id: pluginId,
          plugin_instance: pluginInstance,
        }),
      });
      sessionStorage.setItem(
        "storedMessage",
        JSON.stringify({ type: "success", text: `Success! ${result.message}` })
      );
      location.reload();
      return;
    } catch (error) {
      // Shown in the toast below, so it isn't logged as an error.
      console.debug("Playlist display request failed:", error);
      showResponseModal(
        "failure",
        globalThis.InkyPiHttp.errorMessage(
          error,
          "An error occurred while processing your request."
        )
      );
    }
    setRowBusy(btnEl, false);
    // Disabling the button dropped keyboard focus; put it back for a retry.
    if (btnEl && document.activeElement === document.body) btnEl.focus();
  }

  ns.bindStoredMessageHandler = bindStoredMessageHandler;
  ns.displayPluginInstance = displayPluginInstance;
})(globalThis);

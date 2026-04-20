(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

  let dragSrcEl = null;

  function persistPlaylistOrder(container) {
    const playlistName = container?.getAttribute("data-playlist-name");
    const ordered = Array.from(container.querySelectorAll(".plugin-item")).map(
      (el) => ({
        plugin_id: el.getAttribute("data-plugin-id"),
        name: el.getAttribute("data-instance-name"),
      })
    );
    if (!playlistName || !ordered.length) return;

    fetch(ns.config.reorder_url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ playlist_name: playlistName, ordered }),
    })
      .then(handleJsonResponse)
      .then((result) => {
        if (!result || !result.success) return;
        sessionStorage.setItem(
          "storedMessage",
          JSON.stringify({ type: "success", text: `Success! ${result.message}` })
        );
      })
      .catch(() => showResponseModal("failure", "Error saving new order"));
  }

  function handleDragStart(event) {
    dragSrcEl = this;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", this.id);
    this.classList.add("dragging");
  }

  function handleDragOver(event) {
    if (event.preventDefault) event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    return false;
  }

  function handleDrop(event) {
    if (event.stopPropagation) event.stopPropagation();
    const srcId = event.dataTransfer.getData("text/plain");
    const srcEl = document.getElementById(srcId);
    if (srcEl && srcEl !== this) {
      const srcPlaylist = srcEl.closest(".playlist-item");
      const dstPlaylist = this.closest(".playlist-item");
      if (srcPlaylist !== dstPlaylist) return false;
      this.parentNode.insertBefore(srcEl, this.nextSibling);
      persistPlaylistOrder(this.closest(".playlist-item"));
    }
    return false;
  }

  function handleDragEnd() {
    this.classList.remove("dragging");
  }

  function handleKeyReorder(event) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const item = event.currentTarget;
    const parent = item.parentElement;
    if (!parent) return;

    let target =
      event.key === "ArrowUp"
        ? item.previousElementSibling
        : item.nextElementSibling;
    while (target && !target.classList.contains("plugin-item")) {
      target =
        event.key === "ArrowUp"
          ? target.previousElementSibling
          : target.nextElementSibling;
    }
    if (!target) return;

    if (event.key === "ArrowUp") {
      parent.insertBefore(item, target);
    } else {
      parent.insertBefore(item, target.nextElementSibling);
    }
    persistPlaylistOrder(item.closest(".playlist-item"));
    item.focus();
  }

  function enableDrag(container) {
    const items = container.querySelectorAll(".plugin-item");
    items.forEach((item) => {
      if (item.dataset.playlistDragBound === "1") return;
      if (!item.id) item.id = `plg-${Math.random().toString(36).slice(2)}`;
      item.draggable = true;
      item.tabIndex = 0;
      item.setAttribute("role", "listitem");
      item.addEventListener("dragstart", handleDragStart);
      item.addEventListener("dragover", handleDragOver);
      item.addEventListener("drop", handleDrop);
      item.addEventListener("dragend", handleDragEnd);
      item.addEventListener("keydown", handleKeyReorder);
      item.dataset.playlistDragBound = "1";
    });
  }

  function setPlaylistExpanded(item, expanded, options = {}) {
    const body = item?.querySelector("[data-playlist-body]");
    const toggle = item?.querySelector("[data-playlist-toggle]");
    if (!item || !body || !toggle) return;

    const playlistName = item.getAttribute("data-playlist-name");
    const forceDesktopExpanded = options.forceDesktopExpanded === true;
    const isMobile = !!ns.mobileQuery.matches;
    const shouldExpand = !isMobile && forceDesktopExpanded ? true : !!expanded;

    body.hidden = !shouldExpand;
    item.classList.toggle("mobile-expanded", shouldExpand);
    item.classList.toggle("mobile-collapsed", !shouldExpand);
    toggle.textContent = shouldExpand
      ? toggle.getAttribute("data-expanded-label") || "Hide"
      : toggle.getAttribute("data-collapsed-label") || "Open";
    toggle.setAttribute("aria-expanded", String(shouldExpand));

    if (!isMobile) return;
    if (shouldExpand) {
      ns.state.expandedPlaylist = playlistName;
      return;
    }
    if (ns.state.expandedPlaylist === playlistName) {
      ns.state.expandedPlaylist = null;
    }
  }

  function syncPlaylistCards() {
    const items = Array.from(document.querySelectorAll("[data-playlist-card]"));
    if (!items.length) return;

    if (!ns.mobileQuery.matches) {
      items.forEach((item) =>
        setPlaylistExpanded(item, true, { forceDesktopExpanded: true })
      );
      return;
    }

    const preferred =
      ns.state.expandedPlaylist ||
      items
        .find((item) => item.classList.contains("active"))
        ?.getAttribute("data-playlist-name") ||
      items[0].getAttribute("data-playlist-name");

    items.forEach((item) => {
      const isExpanded = item.getAttribute("data-playlist-name") === preferred;
      setPlaylistExpanded(item, isExpanded);
    });
  }

  function togglePlaylistCard(button) {
    const item = button.closest("[data-playlist-card]");
    if (!item) return;

    const isExpanded =
      button.getAttribute("aria-expanded") === "true" ||
      item.classList.contains("mobile-expanded");
    const willExpand = !isExpanded;

    if (ns.mobileQuery.matches && willExpand) {
      document.querySelectorAll("[data-playlist-card]").forEach((card) => {
        if (card !== item) setPlaylistExpanded(card, false);
      });
    }

    setPlaylistExpanded(item, willExpand);
  }

  function initPlaylistCards() {
    if (ns.runtime.cardsBound) return;
    syncPlaylistCards();
    if (
      !ns.runtime.mobileSyncBound &&
      typeof ns.mobileQuery.addEventListener === "function"
    ) {
      ns.mobileQuery.addEventListener("change", syncPlaylistCards);
      ns.runtime.mobileSyncBound = true;
    }
    ns.runtime.cardsBound = true;
  }

  function initReorderControls() {
    document.querySelectorAll(".playlist-item .plugin-list").forEach(enableDrag);
  }

  Object.assign(ns, {
    enableDrag,
    handleDrop,
    initPlaylistCards,
    initReorderControls,
    persistPlaylistOrder,
    setPlaylistExpanded,
    syncPlaylistCards,
    togglePlaylistCard,
  });
})(globalThis);

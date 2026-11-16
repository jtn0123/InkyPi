(function (global) {
  global.InkyPiPlaylist = global.InkyPiPlaylist || {};
  const ns = global.InkyPiPlaylist;

  function nextPlaylistDragId() {
    ns.runtime.playlistDragCounter = (ns.runtime.playlistDragCounter || 0) + 1;
    return `plg-${ns.runtime.playlistDragCounter}`;
  }

  function capturePlaylistOrder(item) {
    const parent = item?.parentNode;
    const nextSibling = item?.nextSibling;
    return function restorePlaylistOrder() {
      if (!parent || !item) return;
      if (nextSibling && nextSibling.parentNode === parent) {
        parent.insertBefore(item, nextSibling);
        return;
      }
      parent.appendChild(item);
    };
  }

  function persistPlaylistOrder(container, restoreOrder = null) {
    const playlistName = container?.dataset.playlistName;
    const ordered = Array.from(container.querySelectorAll(".plugin-item")).map(
      (el) => ({
        plugin_id: el.dataset.pluginId,
        name: el.dataset.instanceName,
      })
    );
    if (!playlistName || !ordered.length) return;

    fetchJson(ns.config.reorder_url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ playlist_name: playlistName, ordered }),
    })
      .then((result) => {
        showResponseModal("success", `Success! ${result.message || "Order saved"}`);
      })
      .catch((error) => {
        console.debug("Playlist order was not saved:", error);
        restoreOrder?.();
        showResponseModal(
          "failure",
          globalThis.InkyPiHttp.errorMessage(error, "Error saving new order")
        );
      });
  }

  function handleDragStart(event) {
    const item = event.currentTarget;
    item.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", item.id);
  }

  function handleDragOver(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    return false;
  }

  function handleDrop(event) {
    event.stopPropagation();
    const dropTarget = event.currentTarget;
    const srcId = event.dataTransfer.getData("text/plain");
    const srcEl = document.getElementById(srcId);
    if (srcEl && srcEl !== dropTarget) {
      const srcPlaylist = srcEl.closest(".playlist-item");
      const dstPlaylist = dropTarget.closest(".playlist-item");
      if (srcPlaylist !== dstPlaylist) return false;
      const restoreOrder = capturePlaylistOrder(srcEl);
      // Dropped on a row further down: go after it. Further up: go before
      // it, or nothing could ever be dropped into first place.
      const movingDown =
        srcEl.compareDocumentPosition(dropTarget) & Node.DOCUMENT_POSITION_FOLLOWING;
      if (movingDown) {
        dropTarget.after(srcEl);
      } else {
        dropTarget.before(srcEl);
      }
      persistPlaylistOrder(dropTarget.closest(".playlist-item"), restoreOrder);
    }
    return false;
  }

  function handleDragEnd() {
    this.classList.remove("dragging");
  }

  function getAdjacentPlaylistItem(item, direction) {
    let target =
      direction === "up" ? item.previousElementSibling : item.nextElementSibling;
    while (target && !target.classList.contains("plugin-item")) {
      target =
        direction === "up" ? target.previousElementSibling : target.nextElementSibling;
    }
    return target;
  }

  function handleKeyReorder(event) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    // Only the row itself: an arrow key on its Display or Delete button is
    // not a request to move the row.
    if (event.target !== event.currentTarget) return;
    event.preventDefault();
    const item = event.currentTarget;
    const target = getAdjacentPlaylistItem(
      item,
      event.key === "ArrowUp" ? "up" : "down"
    );
    if (!target) return;

    const restoreOrder = capturePlaylistOrder(item);
    if (event.key === "ArrowUp") {
      target.before(item);
    } else {
      target.after(item);
    }
    persistPlaylistOrder(item.closest(".playlist-item"), restoreOrder);
    item.focus();
  }

  function enableDrag(container) {
    const items = container.querySelectorAll(".plugin-item");
    items.forEach((item) => {
      if (item.dataset.playlistDragBound === "1") return;
      if (!item.id) item.id = nextPlaylistDragId();
      item.draggable = true;
      item.tabIndex = 0;
      if (document.getElementById("playlistReorderHint")) {
        item.setAttribute("aria-describedby", "playlistReorderHint");
      }
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

    const playlistName = item.dataset.playlistName;
    const forceDesktopExpanded = options.forceDesktopExpanded === true;
    const isMobile = !!ns.mobileQuery.matches;
    const shouldExpand = !isMobile && forceDesktopExpanded ? true : !!expanded;

    body.hidden = !shouldExpand;
    item.classList.toggle("mobile-expanded", shouldExpand);
    item.classList.toggle("mobile-collapsed", !shouldExpand);
    item.classList.toggle("is-open", shouldExpand);
    const label = shouldExpand
      ? toggle.dataset.expandedLabel || "Hide"
      : toggle.dataset.collapsedLabel || "Open";
    const labelEl = toggle.querySelector(".playlist-toggle-label");
    if (labelEl) {
      labelEl.textContent = label;
    } else {
      toggle.textContent = label;
    }
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
      items.find((item) => item.classList.contains("active"))?.dataset
        .playlistName ||
      items[0].dataset.playlistName;

    items.forEach((item) => {
      const isExpanded = item.dataset.playlistName === preferred;
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
    nextPlaylistDragId,
    persistPlaylistOrder,
    setPlaylistExpanded,
    syncPlaylistCards,
    togglePlaylistCard,
  });
})(globalThis);

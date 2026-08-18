(function () {
  function getOpenHistoryModal() {
    return [
      document.getElementById("deleteHistoryModal"),
      document.getElementById("clearHistoryModal"),
      document.getElementById("lightboxModal"),
    ].find((modal) => modal && !modal.hidden);
  }

  // Module-scope helpers — hoisted from createHistoryPage (JTN-281).
  function setHidden(node, hidden) {
    if (!node) return;
    node.hidden = hidden;
  }

  // Track the element that triggered the most-recently opened modal so
  // focus can be restored when the modal closes (WAI-ARIA best practice).
  let _lastHistoryModalTrigger = null;

  function setModalOpen(node, open, triggerEl) {
    if (!node) return;
    if (open && triggerEl) _lastHistoryModalTrigger = triggerEl;
    node.hidden = !open;
    node.style.display = open ? "flex" : "none";
    node.classList.toggle("is-open", open);
    if (open) {
      // Move focus to the first focusable element inside the modal
      const focusable = node.querySelector(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusable) setTimeout(() => focusable.focus(), 0);
    } else if (_lastHistoryModalTrigger) {
      if (typeof _lastHistoryModalTrigger.focus === "function") {
        _lastHistoryModalTrigger.focus();
      }
      _lastHistoryModalTrigger = null;
    }
  }

  function openClearModal(triggerEl) {
    setModalOpen(document.getElementById("clearHistoryModal"), true, triggerEl);
  }

  function closeClearModal() {
    setModalOpen(document.getElementById("clearHistoryModal"), false);
  }

  function showStoredMessage() {
    const stored = sessionStorage.getItem("storedMessage");
    if (!stored) return;
    try {
      const message = JSON.parse(stored);
      if (message?.type && message.text) {
        showResponseModal(message.type, message.text);
      }
    } catch (e) {
      // Intentionally ignored — malformed session data; item is removed below regardless
    }
    sessionStorage.removeItem("storedMessage");
  }

  function hideHistoryImageSkeleton(img) {
    const skeleton = img.previousElementSibling;
    if (!skeleton) return;
    skeleton.classList.add("is-hidden");
    skeleton.addEventListener(
      "transitionend",
      () => {
        skeleton.style.display = "none";
      },
      { once: true }
    );
  }

  function createHistoryPage(config) {
    const state = {
      pendingDelete: "",
      filter: "all",
      lightboxFilename: "",
      lightboxTrigger: null,
    };

    // Client-side source filter (History v2). Operates on the cards of the
    // current page; re-applied after HTMX pagination swaps so the active
    // filter survives page changes.
    function applyFilter(filter) {
      state.filter = filter;
      document.querySelectorAll("[data-history-filter]").forEach((btn) => {
        const active = btn.dataset.historyFilter === filter;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
      let shown = 0;
      let totalCards = 0;
      document.querySelectorAll(".history-card").forEach((card) => {
        totalCards += 1;
        const match = filter === "all" || card.dataset.category === filter;
        card.hidden = !match;
        if (match) shown += 1;
      });
      document.querySelectorAll("[data-history-group]").forEach((group) => {
        const visible = group.querySelectorAll(
          ".history-card:not([hidden])"
        ).length;
        group.hidden = visible === 0;
        const count = group.querySelector(".history-day-count");
        if (count) {
          count.textContent = `${visible} ${visible === 1 ? "render" : "renders"}`;
        }
      });
      // Say "on this page" whenever the header badge disagrees with our
      // denominator. The filter only ever sees the current page's cards, so
      // with 27 items across two pages this read "24 of 24" directly beneath a
      // "27 items" badge — three numbers, two meanings, and no way to tell
      // whether three renders had gone missing.
      const countEl = document.getElementById("historyShownCount");
      if (countEl) {
        const grandTotal = Number(countEl.dataset.totalItems || totalCards);
        const paginated =
          Number.isFinite(grandTotal) && grandTotal > totalCards;
        countEl.textContent = paginated
          ? `${shown} of ${totalCards} on this page · ${grandTotal} total`
          : `${shown} of ${totalCards}`;
      }
      const emptyEl = document.getElementById("historyFilterEmpty");
      if (emptyEl) emptyEl.hidden = totalCards === 0 || shown > 0;
    }

    async function updateStorage() {
      try {
        const resp = await fetch(config.storageUrl, { cache: "no-store" });
        const data = await resp.json();
        if (!resp.ok) return;
        const block = document.getElementById("storage-block");
        const text = document.getElementById("storage-text");
        const inner = document.getElementById("storage-bar-inner");
        const pct =
          data && data.pct_free !== null && data.pct_free !== undefined
            ? data.pct_free
            : 0;
        setHidden(block, false);
        if (text) {
          text.textContent = `${pct}% free • ${data.free_gb} GB remaining of ${data.total_gb} GB total`;
        }
        if (inner) inner.style.setProperty("--meter-width", `${pct}%`);
      } catch (e) {
        console.error("Failed to update storage", e);
      }
    }

    async function redisplay(filename, button) {
      if (button) button.disabled = true;
      try {
        const resp = await fetch(config.redisplayUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename }),
        });
        const result = await resp.json();
        if (!resp.ok) {
          showResponseModal("failure", `Error! ${result.error}`);
        } else {
          showResponseModal("success", `Success! ${result.message}`);
          updateStorage();
        }
      } catch (e) {
        console.error(e);
        showResponseModal("failure", "Failed to redisplay image. Please try again.");
      } finally {
        if (button) button.disabled = false;
      }
    }

    function openDeleteModal(filename, triggerEl) {
      state.pendingDelete = filename;
      const text = document.getElementById("deleteHistoryText");
      if (text) text.textContent = `Delete this image '${filename}'?`;
      setModalOpen(document.getElementById("deleteHistoryModal"), true, triggerEl);
    }

    function closeDeleteModal() {
      state.pendingDelete = "";
      setModalOpen(document.getElementById("deleteHistoryModal"), false);
    }

    // openClearModal / closeClearModal are at module scope (below) — they
    // don't access createHistoryPage closure variables.

    async function confirmDelete() {
      if (!state.pendingDelete) return;
      const confirmBtn = document.getElementById("confirmDeleteHistoryBtn");
      const cancelBtn = document.getElementById("cancelDeleteHistoryBtn");
      if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.textContent = "Deleting\u2026";
        confirmBtn.classList.add("loading");
      }
      if (cancelBtn) cancelBtn.disabled = true;
      try {
        const resp = await fetch(config.deleteUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: state.pendingDelete }),
        });
        const result = await resp.json();
        if (!resp.ok) {
          closeDeleteModal();
          showResponseModal("failure", "Error! " + result.error);
          return;
        }
        sessionStorage.setItem(
          "storedMessage",
          JSON.stringify({ type: "success", text: "Success! " + result.message })
        );
        globalThis.location.reload();
      } catch (e) {
        console.error(e);
        closeDeleteModal();
        showResponseModal("failure", "Failed to delete image");
      } finally {
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.textContent = "Delete";
          confirmBtn.classList.remove("loading");
        }
        if (cancelBtn) cancelBtn.disabled = false;
      }
    }

    async function confirmClear() {
      const confirmBtn = document.getElementById("confirmClearHistoryBtn");
      const cancelBtn = document.getElementById("cancelClearHistoryBtn");
      if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.textContent = "Clearing\u2026";
        confirmBtn.classList.add("loading");
      }
      if (cancelBtn) cancelBtn.disabled = true;
      try {
        const resp = await fetch(config.clearUrl, { method: "POST" });
        const result = await resp.json();
        if (!resp.ok) {
          closeClearModal();
          showResponseModal("failure", "Error! " + result.error);
          return;
        }
        sessionStorage.setItem(
          "storedMessage",
          JSON.stringify({ type: "success", text: "Success! " + result.message })
        );
        globalThis.location.reload();
      } catch (e) {
        console.error(e);
        closeClearModal();
        showResponseModal("failure", "Failed to clear history");
      } finally {
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.textContent = "Clear";
          confirmBtn.classList.remove("loading");
        }
        if (cancelBtn) cancelBtn.disabled = false;
      }
    }

    function bindImages() {
      document.querySelectorAll(".history-image").forEach((img) => {
        const handler = () => hideHistoryImageSkeleton(img);
        img.addEventListener("load", handler);
        img.addEventListener("error", handler);
        // If the image was already in the browser cache it may have finished
        // loading before this handler attached — in that case the `load`
        // event has already fired and the skeleton would stay stuck on top.
        // Check synchronously and hide the skeleton immediately.
        if (img.complete && img.naturalWidth > 0) {
          hideHistoryImageSkeleton(img);
        }
      });
    }

    // Render-preview lightbox (History v2): shows the full-size image with
    // filename, timestamp/size, source, and Display / Download / Delete.
    function openLightbox(thumb) {
      const modal = document.getElementById("lightboxModal");
      if (!modal) return;
      const filename = thumb.dataset.lightboxFilename || "";
      state.lightboxFilename = filename;
      state.lightboxTrigger = thumb;
      const img = document.getElementById("lightboxImage");
      if (img) {
        img.src = thumb.href;
        img.alt = thumb.getAttribute("aria-label") || "Render preview";
      }
      const name = document.getElementById("lightboxName");
      if (name) {
        name.textContent = filename;
        name.title = filename;
      }
      const sub = document.getElementById("lightboxSub");
      if (sub) sub.textContent = thumb.dataset.lightboxSub || "";
      const source = document.getElementById("lightboxSource");
      if (source) source.textContent = thumb.dataset.lightboxSource || "";
      const download = document.getElementById("lightboxDownloadLink");
      if (download) download.href = thumb.href;
      setModalOpen(modal, true, thumb);
    }

    function closeLightbox() {
      state.lightboxFilename = "";
      setModalOpen(document.getElementById("lightboxModal"), false);
    }

    function bindThumbLightbox() {
      document.addEventListener("click", (event) => {
        const thumb = event.target.closest("a.history-thumb");
        if (!thumb) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        openLightbox(thumb);
      });
    }

    function bindLightboxActions() {
      document
        .getElementById("closeLightboxModalBtn")
        ?.addEventListener("click", closeLightbox);
      document
        .getElementById("lightboxDisplayBtn")
        ?.addEventListener("click", (event) => {
          const filename = state.lightboxFilename;
          if (!filename) return;
          closeLightbox();
          redisplay(filename, event.currentTarget);
        });
      document
        .getElementById("lightboxDeleteBtn")
        ?.addEventListener("click", () => {
          const filename = state.lightboxFilename;
          if (!filename) return;
          const trigger = state.lightboxTrigger;
          closeLightbox();
          openDeleteModal(filename, trigger);
        });
    }

    function bindActions() {
      document
        .getElementById("historyRefreshBtn")
        ?.addEventListener("click", (event) => {
          // Spin the leading icon until the reload lands.
          const btn = event.currentTarget;
          btn.classList.add("loading");
          btn.setAttribute("aria-busy", "true");
          globalThis.location.reload();
        });
      document
        .getElementById("historyClearBtn")
        ?.addEventListener("click", (event) => openClearModal(event.currentTarget));
      document
        .getElementById("confirmDeleteHistoryBtn")
        ?.addEventListener("click", confirmDelete);
      document
        .getElementById("confirmClearHistoryBtn")
        ?.addEventListener("click", confirmClear);
      document
        .getElementById("closeDeleteHistoryModalBtn")
        ?.addEventListener("click", closeDeleteModal);
      document
        .getElementById("cancelDeleteHistoryBtn")
        ?.addEventListener("click", closeDeleteModal);
      document
        .getElementById("closeClearHistoryModalBtn")
        ?.addEventListener("click", closeClearModal);
      document
        .getElementById("cancelClearHistoryBtn")
        ?.addEventListener("click", closeClearModal);

      document.addEventListener("click", (event) => {
        const filterButton = event.target.closest("[data-history-filter]");
        if (filterButton) {
          applyFilter(filterButton.dataset.historyFilter || "all");
          return;
        }

        const actionButton = event.target.closest("[data-history-action]");
        if (actionButton) {
          const action = actionButton.dataset.historyAction;
          const filename = actionButton.dataset.filename;
          if (action === "display" && filename) {
            redisplay(filename, actionButton);
          } else if (action === "delete" && filename) {
            openDeleteModal(filename, actionButton);
          }
          return;
        }

        if (event.target === document.getElementById("deleteHistoryModal")) {
          closeDeleteModal();
        }
        if (event.target === document.getElementById("clearHistoryModal")) {
          closeClearModal();
        }
        if (event.target === document.getElementById("lightboxModal")) {
          closeLightbox();
        }
      });

      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        const openModal = getOpenHistoryModal();
        if (!openModal) return;
        event.preventDefault();
        if (openModal.id === "deleteHistoryModal") {
          closeDeleteModal();
        } else if (openModal.id === "clearHistoryModal") {
          closeClearModal();
        } else if (openModal.id === "lightboxModal") {
          closeLightbox();
        }
      });
    }

    function init() {
      showStoredMessage();
      updateStorage();
      bindImages();
      bindThumbLightbox();
      bindLightboxActions();
      bindActions();
      globalThis.updateHistoryStorage = updateStorage;

      // Re-bind skeleton handlers after HTMX swaps new grid content.
      // The htmx:afterSettle event fires after the DOM has fully settled,
      // ensuring the new images are available for binding.
      document.body.addEventListener("htmx:afterSettle", function () {
        bindImages();
        // The swapped-in grid renders unfiltered with an "All"-state toolbar;
        // re-apply the active filter so it survives pagination.
        applyFilter(state.filter);
      });
    }

    return { init };
  }

  globalThis.InkyPiHistoryPage = { create: createHistoryPage };
})();

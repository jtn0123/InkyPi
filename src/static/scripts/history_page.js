(function () {
  function createHistoryPage(config) {
    const state = {
      pendingDelete: "",
    };

    function setHidden(node, hidden) {
      if (!node) return;
      node.hidden = hidden;
    }

    function setModalOpen(node, open) {
      if (!node) return;
      node.hidden = !open;
      node.style.display = open ? "block" : "none";
    }

    function showStoredMessage() {
      const stored = sessionStorage.getItem("storedMessage");
      if (!stored) return;
      try {
        const message = JSON.parse(stored);
        if (message && message.type && message.text) {
          showResponseModal(message.type, message.text);
        }
      } catch (e) {}
      sessionStorage.removeItem("storedMessage");
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
        if (inner) inner.style.width = `${pct}%`;
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

    function openDeleteModal(filename) {
      state.pendingDelete = filename;
      const text = document.getElementById("deleteHistoryText");
      if (text) text.textContent = `Delete this image '${filename}'?`;
      setModalOpen(document.getElementById("deleteHistoryModal"), true);
    }

    function closeDeleteModal() {
      state.pendingDelete = "";
      setModalOpen(document.getElementById("deleteHistoryModal"), false);
    }

    function openClearModal() {
      setModalOpen(document.getElementById("clearHistoryModal"), true);
    }

    function closeClearModal() {
      setModalOpen(document.getElementById("clearHistoryModal"), false);
    }

    async function confirmDelete() {
      if (!state.pendingDelete) return;
      try {
        const resp = await fetch(config.deleteUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: state.pendingDelete }),
        });
        const result = await resp.json();
        if (!resp.ok) {
          showResponseModal("failure", `Error! ${result.error}`);
          return;
        }
        sessionStorage.setItem(
          "storedMessage",
          JSON.stringify({ type: "success", text: `Success! ${result.message}` })
        );
        window.location.reload();
      } catch (e) {
        console.error(e);
        showResponseModal("failure", "Failed to delete image");
      } finally {
        closeDeleteModal();
      }
    }

    async function confirmClear() {
      try {
        const resp = await fetch(config.clearUrl, { method: "POST" });
        const result = await resp.json();
        if (!resp.ok) {
          showResponseModal("failure", `Error! ${result.error}`);
          return;
        }
        sessionStorage.setItem(
          "storedMessage",
          JSON.stringify({ type: "success", text: `Success! ${result.message}` })
        );
        window.location.reload();
      } catch (e) {
        console.error(e);
        showResponseModal("failure", "Failed to clear history");
      } finally {
        closeClearModal();
      }
    }

    function bindImages() {
      document.querySelectorAll(".history-image").forEach((img) => {
        function hideSkeleton() {
          const skeleton = img.previousElementSibling;
          if (skeleton) skeleton.style.display = "none";
        }
        img.addEventListener("load", hideSkeleton);
        img.addEventListener("error", hideSkeleton);
      });
    }

    function bindThumbLightbox() {
      document.addEventListener("click", (event) => {
        const thumb = event.target.closest("a.history-thumb");
        if (!thumb) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        const img = thumb.querySelector("img");
        const alt =
          thumb.getAttribute("aria-label") || (img && img.alt) || "Preview";
        if (window.Lightbox) {
          window.Lightbox.open(thumb.href, alt);
        }
      });
    }

    function bindActions() {
      document
        .getElementById("historyRefreshBtn")
        ?.addEventListener("click", () => window.location.reload());
      document
        .getElementById("historyClearBtn")
        ?.addEventListener("click", openClearModal);
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
        const actionButton = event.target.closest("[data-history-action]");
        if (actionButton) {
          const action = actionButton.dataset.historyAction;
          const filename = actionButton.dataset.filename;
          if (action === "display" && filename) {
            redisplay(filename, actionButton);
          } else if (action === "delete" && filename) {
            openDeleteModal(filename);
          }
          return;
        }

        if (event.target === document.getElementById("deleteHistoryModal")) {
          closeDeleteModal();
        }
        if (event.target === document.getElementById("clearHistoryModal")) {
          closeClearModal();
        }
      });
    }

    function init() {
      showStoredMessage();
      updateStorage();
      bindImages();
      bindThumbLightbox();
      bindActions();
      window.updateHistoryStorage = updateStorage;
    }

    return { init };
  }

  window.InkyPiHistoryPage = { create: createHistoryPage };
})();

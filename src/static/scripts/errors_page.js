(function () {
  "use strict";

  function setModalOpen(node, open) {
    if (!node) return;
    node.hidden = !open;
    node.style.display = open ? "block" : "none";
  }

  function getClearModal() {
    return document.getElementById("clearErrorsModal");
  }

  function openClearModal() {
    setModalOpen(getClearModal(), true);
  }

  function closeClearModal() {
    setModalOpen(getClearModal(), false);
  }

  async function confirmClear() {
    var confirmBtn = document.getElementById("confirmClearErrorsBtn");
    var cancelBtn = document.getElementById("cancelClearErrorsBtn");
    var clearUrl = (document.getElementById("errorsBootData") || {}).dataset
      ? document.getElementById("errorsBootData").dataset.clearUrl
      : "/errors/clear";

    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Clearing\u2026";
      confirmBtn.classList.add("loading");
    }
    if (cancelBtn) cancelBtn.disabled = true;

    try {
      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      var csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";

      var resp = await fetch(clearUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
      });
      var result = await resp.json();
      if (!resp.ok) {
        closeClearModal();
        if (globalThis.showResponseModal) {
          showResponseModal("failure", "Error! " + (result.error || "Clear failed"));
        }
        return;
      }
      closeClearModal();
      // Remove all rendered error rows
      var tbody = document.getElementById("errorsTableBody");
      if (tbody) {
        tbody.innerHTML = "";
      }
      var emptyState = document.getElementById("errorsEmptyState");
      if (emptyState) {
        emptyState.hidden = false;
      }
      var clearBtn = document.getElementById("errorsClearBtn");
      if (clearBtn) {
        clearBtn.disabled = true;
      }
      if (globalThis.showResponseModal) {
        showResponseModal("success", "Error logs cleared.");
      }
    } catch (e) {
      console.error("Failed to clear error logs", e);
      closeClearModal();
      if (globalThis.showResponseModal) {
        showResponseModal("failure", "Failed to clear error logs. Please try again.");
      }
    } finally {
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = "Clear All";
        confirmBtn.classList.remove("loading");
      }
      if (cancelBtn) cancelBtn.disabled = false;
    }
  }

  function bindActions() {
    document
      .getElementById("errorsClearBtn")
      ?.addEventListener("click", openClearModal);

    document
      .getElementById("confirmClearErrorsBtn")
      ?.addEventListener("click", confirmClear);

    document
      .getElementById("cancelClearErrorsBtn")
      ?.addEventListener("click", closeClearModal);

    document
      .getElementById("closeClearErrorsModalBtn")
      ?.addEventListener("click", closeClearModal);

    // Close on backdrop click
    document.addEventListener("click", function (event) {
      if (event.target === getClearModal()) {
        closeClearModal();
      }
    });

    // Close on Escape
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      var modal = getClearModal();
      if (!modal || modal.hidden) return;
      event.preventDefault();
      closeClearModal();
    });
  }

  document.addEventListener("DOMContentLoaded", bindActions);
})();

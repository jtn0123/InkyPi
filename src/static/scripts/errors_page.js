(function () {
  "use strict";

  function getClearModal() {
    return document.getElementById("clearErrorsModal");
  }

  // The shared helper moves focus into the dialog, keeps Tab inside it,
  // closes it on Escape and hands focus back to the button that opened it.
  function openClearModal(event) {
    var modal = getClearModal();
    if (!modal) return;
    modal.hidden = false;
    modal.style.display = "block";
    globalThis.InkyPiModalFocus?.activate(
      modal,
      event?.currentTarget || document.activeElement,
      closeClearModal
    );
  }

  function closeClearModal() {
    var modal = getClearModal();
    if (!modal) return;
    modal.hidden = true;
    modal.style.display = "none";
    globalThis.InkyPiModalFocus?.deactivate(modal);
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
      const resp = await fetch(clearUrl, {
        method: "POST",
        headers: { "X-CSRFToken": globalThis.InkyPiCsrf?.getToken() || "" },
      });
      const result = await resp.json();
      if (!resp.ok) {
        closeClearModal();
        if (globalThis.showResponseModal) {
          showResponseModal("failure", "Error! " + (result.error || "Clear failed"));
        }
        return;
      }
      closeClearModal();
      // Remove all rendered error rows
      const tbody = document.getElementById("errorsTableBody");
      if (tbody) {
        tbody.innerHTML = "";
      }
      const emptyState = document.getElementById("errorsEmptyState");
      if (emptyState) {
        emptyState.hidden = false;
      }
      const clearBtn = document.getElementById("errorsClearBtn");
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
  }

  document.addEventListener("DOMContentLoaded", bindActions);
})();

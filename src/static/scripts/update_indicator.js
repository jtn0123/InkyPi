// Global update indicator + quick-update confirm flow.
//
// Polls /api/version once per page load. When an update is available the
// sidebar download button unhides; clicking it opens the shared confirm
// modal rendered in base.html. Confirming POSTs /settings/update, shows a
// toast, and forwards the user to /settings so they can watch the log
// stream take over.
(function () {
  "use strict";

  // Session cache so every navigation inside the same tab doesn't re-hit
  // /api/version. A 10-minute TTL keeps the indicator reasonably fresh
  // without pounding GitHub when the user tab-hops through the UI.
  const CACHE_KEY = "inkypi-update-check";
  const CACHE_TTL_MS = 10 * 60 * 1000;

  function getCachedVersion() {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      if (typeof parsed.ts !== "number" || Date.now() - parsed.ts > CACHE_TTL_MS) {
        return null;
      }
      return parsed.data;
    } catch (e) {
      return null;
    }
  }

  function setCachedVersion(data) {
    try {
      sessionStorage.setItem(
        CACHE_KEY,
        JSON.stringify({ ts: Date.now(), data })
      );
    } catch (e) {}
  }

  async function fetchVersion(signal) {
    const response = await fetch("/api/version", {
      cache: "no-store",
      signal,
    });
    if (!response.ok) {
      throw new Error("version check failed: " + response.status);
    }
    return await response.json();
  }

  function showIndicator(btn, data) {
    if (!btn) return;
    btn.hidden = false;
    const label = "Update available: v" + String(data.latest).replace(/^v/, "");
    btn.setAttribute("aria-label", label);
    btn.setAttribute("title", label);
    btn.dataset.latest = data.latest || "";
    btn.dataset.current = data.current || "";
    btn.dataset.releaseNotes = data.release_notes || "";
  }

  function hideIndicator(btn) {
    if (!btn) return;
    btn.hidden = true;
  }

  function openModal(modal) {
    if (!modal) return;
    modal.hidden = false;
    modal.style.display = "block";
    modal.classList.add("is-open");
    document.body.classList.add("modal-open");
    const confirmBtn = modal.querySelector("#quickUpdateStartBtn");
    if (confirmBtn) confirmBtn.focus();
  }

  function closeModal(modal) {
    if (!modal) return;
    modal.hidden = true;
    modal.style.display = "none";
    modal.classList.remove("is-open");
    document.body.classList.remove("modal-open");
  }

  function populateModal(modal, btn) {
    if (!modal || !btn) return;
    const latestEl = modal.querySelector("#quickUpdateLatest");
    const currentEl = modal.querySelector("#quickUpdateCurrent");
    if (latestEl) {
      latestEl.textContent = btn.dataset.latest
        ? "v" + String(btn.dataset.latest).replace(/^v/, "")
        : "\u2014";
    }
    if (currentEl) {
      currentEl.textContent = btn.dataset.current
        ? "v" + String(btn.dataset.current).replace(/^v/, "")
        : "\u2014";
    }
  }

  async function startUpdate(modal) {
    const confirmBtn = modal.querySelector("#quickUpdateStartBtn");
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Starting…";
    }
    try {
      const response = await fetch("/settings/update", { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) {
        const err = (data && data.error) || "Failed to start update";
        if (typeof window.showResponseModal === "function") {
          window.showResponseModal("failure", err);
        } else {
          alert(err);
        }
        return;
      }
      if (typeof window.showResponseModal === "function") {
        window.showResponseModal(
          "success",
          data.message || "Update started. Streaming progress on Settings → Updates."
        );
      }
      closeModal(modal);
      // Redirect to settings so the user can watch the log stream take
      // over. On the settings page, actions.js already polls update
      // status and will show the spinner / completion banner.
      if (!location.pathname.startsWith("/settings")) {
        setTimeout(() => {
          location.href = "/settings#section-software-update";
        }, 600);
      }
    } catch (e) {
      if (typeof window.showResponseModal === "function") {
        window.showResponseModal("failure", "Failed to start update");
      }
    } finally {
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = "Update now";
      }
    }
  }

  function wireModal(modal, btn) {
    if (!modal) return;
    const closeEls = [
      modal.querySelector("#closeQuickUpdateBtn"),
      modal.querySelector("#quickUpdateCancelBtn"),
    ];
    for (const el of closeEls) {
      if (el) el.addEventListener("click", () => closeModal(modal));
    }
    // Clicking the backdrop (not the content) closes the modal.
    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeModal(modal);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.hidden) closeModal(modal);
    });
    const confirmBtn = modal.querySelector("#quickUpdateStartBtn");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", () => startUpdate(modal));
    }
    // Close the modal when the release-notes link is clicked; the anchor
    // then navigates naturally to /settings#section-software-update.
    const detailsLink = modal.querySelector("#quickUpdateDetailsLink");
    if (detailsLink) {
      detailsLink.addEventListener("click", () => closeModal(modal));
    }
    if (btn) {
      btn.addEventListener("click", () => {
        populateModal(modal, btn);
        openModal(modal);
      });
    }
  }

  async function init() {
    const btn = document.getElementById("sidebarUpdateBtn");
    const modal = document.getElementById("quickUpdateModal");
    if (!btn || !modal) return;
    wireModal(modal, btn);

    // Apply cached state synchronously so the indicator doesn't flicker
    // on hot navigations within the same session.
    const cached = getCachedVersion();
    if (cached && cached.update_available && !cached.update_running) {
      showIndicator(btn, cached);
    }

    // Skip the network call while an update is actively running — the
    // Settings page already polls status and the answer would be stale
    // anyway.
    if (cached && cached.update_running) {
      hideIndicator(btn);
      return;
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const data = await fetchVersion(controller.signal);
      setCachedVersion(data);
      if (data.update_available && !data.update_running) {
        showIndicator(btn, data);
      } else {
        hideIndicator(btn);
      }
    } catch (e) {
      // Silent — no indicator until the next successful check. A chip on
      // the Settings page surfaces check failures to users who care.
    } finally {
      clearTimeout(timeout);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Expose for tests.
  window.InkyPiUpdateIndicator = {
    init,
    showIndicator,
    hideIndicator,
    openModal,
    closeModal,
    populateModal,
  };
})();

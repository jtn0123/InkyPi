/* Shared helpers for the plugin detail page controller. */
(function () {
  "use strict";

  function validateAddToPlaylistAction(action) {
    if (action !== "add_to_playlist") return true;
    const instanceInput = document.getElementById("instance");
    const instanceError = document.getElementById("instance-error");
    const name = (instanceInput?.value || "").trim();
    if (!name) {
      if (instanceInput) {
        instanceInput.setAttribute("aria-invalid", "true");
        instanceInput.focus();
      }
      if (instanceError) instanceError.textContent = "Instance name is required";
      return false;
    }
    if (!/^[A-Za-z0-9 _-]+$/.test(name)) {
      if (instanceInput) {
        instanceInput.setAttribute("aria-invalid", "true");
        instanceInput.focus();
      }
      if (instanceError) {
        instanceError.textContent =
          "Instance name can only contain letters, numbers, spaces, underscores, and hyphens";
      }
      return false;
    }
    if (instanceInput) instanceInput.setAttribute("aria-invalid", "false");
    if (instanceError) instanceError.textContent = "";
    return true;
  }

  function syncModalOpenState(ui) {
    if (ui?.syncModalOpenState) return ui.syncModalOpenState();
    const open = document.querySelector(".modal.is-open");
    document.body.classList.toggle("modal-open", !!open);
  }

  function setHidden(node, hidden) {
    if (!node) return;
    node.hidden = hidden;
    node.classList.toggle("is-hidden", hidden);
  }

  function buildProgressKey(ctx, config) {
    if (ctx?.page === "plugin") {
      const pid = ctx.pluginId || config.pluginId;
      const inst = ctx.instance || "";
      return `INKYPI_LAST_PROGRESS:plugin:${pid}:${inst || "_"}`;
    }
    return "INKYPI_LAST_PROGRESS";
  }

  function fadeSkeleton(skel) {
    if (!skel) return;
    skel.classList.add("is-hidden");
    skel.addEventListener(
      "transitionend",
      () => {
        skel.style.display = "none";
      },
      { once: true }
    );
  }

  function showInstanceFallback(imgEl, skeleton, fallback) {
    setHidden(imgEl, true);
    setHidden(skeleton, true);
    setHidden(fallback, false);
  }

  function updateCombinedColorPreview(combined, bgPicker, textPicker) {
    combined.style.background = bgPicker.value;
    combined.style.color = textPicker.value;
  }

  function ensureInlineValidationMessages(result) {
    if (!result || !Array.isArray(result.invalid)) return;
    result.invalid.forEach(({ input, message }) => {
      if (!input) return;
      const group = input.closest(".form-group") || input.parentElement;
      if (!group) return;
      let messageEl = null;
      const describedByTokens = (input.getAttribute("aria-describedby") || "")
        .trim()
        .split(/\s+/)
        .filter(Boolean);
      for (const token of describedByTokens) {
        const candidate = document.getElementById(token);
        if (candidate?.classList.contains("validation-message")) {
          messageEl = candidate;
          break;
        }
      }
      if (!messageEl) {
        messageEl = document.createElement("span");
        messageEl.className = "validation-message";
        messageEl.setAttribute("role", "alert");
        const baseId = input.id || input.name || "field";
        messageEl.id = `${baseId}-error`;
        group.appendChild(messageEl);
        if (!describedByTokens.includes(messageEl.id)) {
          describedByTokens.push(messageEl.id);
        }
        input.setAttribute("aria-describedby", describedByTokens.join(" "));
      }
      input.setAttribute("aria-invalid", "true");
      messageEl.textContent = message || "This field is invalid";
      messageEl.style.display = "";
    });
  }

  function setCurrentDisplayRefresh(value) {
    const currTime = document.getElementById("currentDisplayTime");
    if (!currTime) return;
    currTime.textContent = value ? new Date(value).toLocaleString() : "—";
  }

  function initScheduleFormState() {
    const form = document.getElementById("scheduleForm");
    if (!form) return;
    const button = form.querySelector("[data-schedule-submit]");
    const instanceInput = document.getElementById("instance");
    const intervalRadio = document.getElementById("refreshTypeInterval");
    const scheduledRadio = document.getElementById("refreshTypeScheduled");
    const intervalInput = document.getElementById("scheduleInterval");
    const unitInput = document.getElementById("scheduleUnit");
    const timeInput = document.getElementById("scheduleTime");
    const apiKeyMissing = button?.dataset.apiKeyMissing === "true";

    function isInstanceValid() {
      const value = (instanceInput?.value || "").trim();
      return !!value && /^[A-Za-z0-9 _-]+$/.test(value);
    }

    function isCadenceValid() {
      if (scheduledRadio?.checked) return !!timeInput?.value;
      const min = Number(intervalInput?.min || 1);
      return Number(intervalInput?.value) >= min;
    }

    function sync() {
      const scheduled = !!scheduledRadio?.checked;
      if (intervalInput) intervalInput.disabled = scheduled;
      if (unitInput) unitInput.disabled = scheduled;
      if (timeInput) timeInput.disabled = !scheduled;
      if (!button || apiKeyMissing) return;
      const valid = isInstanceValid() && isCadenceValid();
      button.disabled = !valid;
      button.setAttribute("aria-disabled", valid ? "false" : "true");
      button.title = valid ? "" : "Complete the schedule fields first";
    }

    [instanceInput, intervalInput, unitInput, timeInput].forEach((input) => {
      input?.addEventListener("input", sync);
      input?.addEventListener("change", sync);
    });
    [intervalRadio, scheduledRadio].forEach((input) => {
      input?.addEventListener("change", sync);
    });
    sync();
  }

  function setPluginSubtab(id) {
    document.querySelectorAll("[data-plugin-subtab]").forEach((btn) => {
      const active = btn.dataset.pluginSubtab === id;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
      btn.setAttribute("tabindex", active ? "0" : "-1");
    });
    document.querySelectorAll("[data-plugin-subpanel]").forEach((panel) => {
      const active = panel.dataset.pluginSubpanel === id;
      panel.hidden = !active;
      panel.setAttribute("aria-hidden", active ? "false" : "true");
    });
  }

  globalThis.InkyPiPluginPageShared = {
    buildProgressKey,
    ensureInlineValidationMessages,
    fadeSkeleton,
    initScheduleFormState,
    setCurrentDisplayRefresh,
    setHidden,
    setPluginSubtab,
    showInstanceFallback,
    syncModalOpenState,
    updateCombinedColorPreview,
    validateAddToPlaylistAction,
  };
})();

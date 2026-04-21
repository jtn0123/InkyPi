(function () {
  // Module-scoped DOM helpers for the delete button inside a managed API key
  // card. Hoisted out of `createApiKeysPage` because they don't close over any
  // state (SonarCloud javascript:S7721).
  function _cardForSection(sectionId) {
    return document
      .getElementById(`${sectionId}-status`)
      ?.closest(".api-key-card");
  }

  // Helper — find the label for a given provider key_name by reading the
  // <label for=INPUT_ID> text inside the same card. Used to produce accurate
  // delete-button aria-labels after a save without hard-coding names.
  function _labelForCard(card) {
    const label = card?.querySelector(".api-key-card-head .key-svc");
    return label ? (label.textContent || "").trim() : "";
  }

  function addDeleteButton(sectionId, keyName) {
    // The Delete button lives inside `.api-key-actions` (the input row), NOT
    // `.api-key-card-head` (which holds the label + status). Walk up to the
    // card and then into the actions container so new buttons land next to
    // the input rather than next to the status line.
    const card = _cardForSection(sectionId);
    const actions = card?.querySelector(".api-key-actions");
    if (!actions) return;
    if (
      !actions.querySelector('.delete-button[data-api-action="delete-key"]')
    ) {
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "header-button delete-button delete-button-danger";
      deleteButton.dataset.apiAction = "delete-key";
      deleteButton.dataset.keyName = keyName;
      deleteButton.dataset.testSkipClick = "true";
      deleteButton.setAttribute(
        "aria-label",
        `Delete ${_labelForCard(card) || keyName} key permanently`
      );
      deleteButton.title = "Permanently remove key from .env";
      deleteButton.textContent = "Delete";
      actions.appendChild(deleteButton);
    }
  }

  function removeDeleteButton(sectionId) {
    const card = _cardForSection(sectionId);
    card
      ?.querySelector(
        '.api-key-actions .delete-button[data-api-action="delete-key"]'
      )
      ?.remove();
  }

  function setToggleLabel(toggle, label) {
    const textNode = toggle?.querySelector("[data-role='toggle-label']");
    if (textNode) {
      textNode.textContent = label;
      return;
    }
    if (toggle) toggle.textContent = label;
  }

  // Sub-helpers extracted from setCardConfigured to stay under the
  // cognitive-complexity threshold (SonarCloud javascript:S3776).
  function _updateKeyChip(card, configured) {
    const chip = card.querySelector("[data-role='key-chip']");
    if (!chip) return;
    chip.classList.toggle("success", !!configured);
    chip.classList.toggle("warning", !configured);
    chip.textContent = configured ? "Configured" : "Not set";
  }

  function _updateKeyToggle(card, configured) {
    const toggle = card.querySelector(".api-key-toggle");
    if (!toggle) return;
    const visibleLabel = configured ? "Change" : "Add key";
    // Keep the accessible name in sync with the visible label so
    // screen-reader users and tooltip consumers don't see stale copy
    // after a save/delete transition.
    const actionLabel = configured ? "Change" : "Add";
    const providerLabel = _labelForCard(card);
    const accessibleLabel = providerLabel
      ? `${actionLabel} ${providerLabel} key`
      : visibleLabel;
    setToggleLabel(toggle, visibleLabel);
    if (toggle.hasAttribute("aria-label")) {
      toggle.setAttribute("aria-label", accessibleLabel);
    }
    if (toggle.hasAttribute("title")) {
      toggle.title = accessibleLabel;
    }
    toggle.classList.toggle("is-secondary", !!configured);
    toggle.setAttribute("aria-expanded", "false");
  }

  // Transition a card's visible chip / toggle button between the configured
  // and "not set" states without reloading the page. Called from the
  // save-success and delete-success paths so users see immediate feedback.
  function setCardConfigured(card, configured) {
    if (!card) return;
    card.dataset.configured = configured ? "true" : "false";
    _updateKeyChip(card, configured);
    _updateKeyToggle(card, configured);
    // Ensure the input row is collapsed again after a successful save/delete.
    const actions = card.querySelector(".api-key-actions");
    if (actions) actions.setAttribute("hidden", "");
  }

  // Mapping for managed-key providers. Hoisted above the functions that
  // consume it so updateConfiguredStatus / updateDeletedStatus can live at
  // module scope (SonarCloud javascript:S7721 — no closure use required).
  const MANAGED_KEY_MAPPING = {
    OPEN_AI_SECRET: ["openai-status", "openai-input", "openai"],
    OPEN_WEATHER_MAP_SECRET: [
      "openweather-status",
      "openweather-input",
      "openweather",
    ],
    NASA_SECRET: ["nasa-status", "nasa-input", "nasa"],
    UNSPLASH_ACCESS_KEY: ["unsplash-status", "unsplash-input", "unsplash"],
    GITHUB_SECRET: ["github-status", "github-input", "github"],
    GOOGLE_AI_SECRET: ["googleai-status", "googleai-input", "googleai"],
  };

  // Mirror the server's `mask()` helper in src/blueprints/settings/_config.py
  // so the transient post-save state matches what the server will render on
  // reload (CodeRabbit review, PR #570). If the algorithms ever diverge the
  // worst case is a cosmetic flash between save and next navigation.
  function _maskApiKeyValue(value) {
    if (!value) return "";
    if (value.length >= 4) {
      return `...${value.slice(-4)} (${value.length} chars)`;
    }
    return `set (${value.length} chars)`;
  }

  function _upsertMaskChip(card, maskedValue) {
    if (!card || !maskedValue) return;
    const target = card.querySelector(".key-row-right");
    if (!target) return;
    let chip = target.querySelector(".api-mask");
    if (!chip) {
      chip = document.createElement("span");
      chip.className = "api-mask mono";
      chip.setAttribute("aria-hidden", "true");
      target.insertBefore(chip, target.firstChild);
    }
    chip.textContent = maskedValue;
  }

  function updateConfiguredStatus(updatedKeys) {
    updatedKeys.forEach((key) => {
      const entry = MANAGED_KEY_MAPPING[key];
      if (!entry) return;
      const [statusId, inputId, sectionId] = entry;
      const statusElement = document.getElementById(statusId);
      const inputElement = document.getElementById(inputId);
      const value = inputElement ? inputElement.value : "";
      if (statusElement && value) {
        statusElement.textContent = "";
        const strong1 = document.createElement("strong");
        strong1.textContent = "Status:";
        statusElement.appendChild(strong1);
        statusElement.appendChild(document.createTextNode(" Configured"));
        // Insert/update the masked-key preview pill so the card's transient
        // state matches the server-rendered version after a reload.
        _upsertMaskChip(_cardForSection(sectionId), _maskApiKeyValue(value));
        // Clear the input and update its placeholder so subsequent edits
        // start from empty rather than appending to the prior entry.
        inputElement.value = "";
        inputElement.placeholder = "(leave blank to keep current)";
        addDeleteButton(sectionId, key);
        setCardConfigured(_cardForSection(sectionId), true);
      }
    });
  }

  function updateDeletedStatus(keyName) {
    const entry = MANAGED_KEY_MAPPING[keyName];
    if (!entry) return;
    const [statusId, inputId, sectionId] = entry;
    const statusElement = document.getElementById(statusId);
    const inputElement = document.getElementById(inputId);
    if (statusElement) {
      statusElement.textContent = "";
      const strong3 = document.createElement("strong");
      strong3.textContent = "Status:";
      statusElement.appendChild(strong3);
      statusElement.appendChild(document.createTextNode(" Not configured"));
    }
    if (inputElement) {
      inputElement.value = "";
      inputElement.placeholder =
        inputElement.dataset.emptyPlaceholder || "Enter API key";
    }
    removeDeleteButton(sectionId);
    const card = _cardForSection(sectionId);
    setCardConfigured(card, false);
    // Also remove the "Configured" mask chip since the key is gone.
    card?.querySelector(".api-mask")?.remove();
  }

  // Reveal the hidden .api-key-actions container (which holds the password
  // input and optional Delete button) for a managed-key card. The card
  // starts collapsed so the UI is a compact summary row; clicking
  // "Change" / "Add key" expands it and focuses the input. Hoisted because
  // it closes over no createApiKeysPage state (SonarCloud javascript:S7721).
  function revealInput(button) {
    const inputId = button.dataset.inputId;
    if (!inputId) return;
    const input = document.getElementById(inputId);
    if (!input) return;
    const actions = input.closest(".api-key-actions");
    if (!actions) return;
    actions.removeAttribute("hidden");
    button.setAttribute("aria-expanded", "true");
    try {
      input.focus();
    } catch {
      // focus() can throw if the input became detached between the lookup
      // above and this call (e.g. concurrent re-render). Swallow rather than
      // surface a blocking error — the reveal itself already succeeded.
    }
  }

  function createApiKeysPage(config) {
    // Dirty-tracking state: true when any field has changed since last save/load.
    let _isDirty = false;

    // Monotonic suffix for unique id/name/label on JS-built rows (JTN-383).
    // Each call to addRow bumps this so assistive-tech and autofill can
    // distinguish the inputs even when multiple rows are added in a session.
    let _rowCounter = 0;

    function markDirty() {
      _isDirty = true;
      const saveBtn = document.getElementById("saveApiKeysBtn");
      if (saveBtn) saveBtn.disabled = false;
    }

    function markClean() {
      _isDirty = false;
      const saveBtn = document.getElementById("saveApiKeysBtn");
      if (saveBtn) saveBtn.disabled = true;
    }

    // Extracted to keep saveManagedKeys below the cognitive-complexity
    // threshold (SonarCloud javascript:S3776). Shows the appropriate modal
    // for a successful resp.ok response and refreshes the configured-status
    // UI for keys that were actually written.
    function handleManagedSaveSuccess(result) {
      const skipped = Array.isArray(result.skipped_placeholder)
        ? result.skipped_placeholder
        : [];
      if (skipped.length > 0) {
        // Some values were rejected as bullet-character placeholders
        // (JTN-598). Tell the user which ones so they can retype if they
        // actually wanted to update those keys.
        showResponseModal(
          "failure",
          `Saved with warnings. Skipped placeholder-only values for: ${skipped.join(
            ", "
          )}. Type a real key and save again to update these.`
        );
      } else {
        showResponseModal("success", `Success! ${result.message}`);
      }
      if (result.updated && result.updated.length > 0) {
        updateConfiguredStatus(result.updated);
      }
    }

    function finalizeSaveButton(saveBtn, savedOk) {
      if (!saveBtn) return;
      saveBtn.textContent = "Save API keys";
      if (savedOk) {
        markClean();
      } else {
        // Re-enable so user can retry
        saveBtn.disabled = false;
      }
    }

    async function saveManagedKeys() {
      const form = document.getElementById("apiKeysForm");
      const saveBtn = document.getElementById("saveApiKeysBtn");
      if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "Saving\u2026"; }
      const data = new FormData(form);
      let savedOk = false;
      try {
        const resp = await fetch(config.saveManagedUrl, {
          method: "POST",
          body: data,
        });
        const result = await resp.json();
        if (resp.ok) {
          savedOk = true;
          handleManagedSaveSuccess(result);
        } else {
          showResponseModal("failure", `Error! ${result.error}`);
        }
      } catch (e) {
        showResponseModal("failure", "Failed to save keys. Please try again.");
      } finally {
        finalizeSaveButton(saveBtn, savedOk);
      }
    }

    async function deleteKey(keyName) {
      if (!confirm(`Delete the ${keyName} API key? This cannot be undone.`)) return;
      const data = new FormData();
      data.append("key", keyName);
      try {
        const resp = await fetch(config.deleteManagedUrl, {
          method: "POST",
          body: data,
        });
        const result = await resp.json();
        if (resp.ok) {
          showResponseModal("success", `Success! ${result.message}`);
          updateDeletedStatus(keyName);
        } else {
          showResponseModal("failure", `Error! ${result.error}`);
        }
      } catch (e) {
        showResponseModal("failure", "Failed to delete key. Please try again.");
      }
    }

    // Keep delete-button + value-input aria-labels in sync with the current
    // key name so assistive tech hears "API key value for OPEN_AI_SECRET"
    // instead of the generic "API key value" after the user types a name.
    function updateRowAriaLabels(row, keyName) {
      const trimmed = (keyName || "").trim();
      const valInput = row.querySelector(".apikey-value");
      const delBtn = row.querySelector(".btn-delete");
      if (valInput) {
        valInput.setAttribute(
          "aria-label",
          trimmed ? `API key value for ${trimmed}` : "API key value"
        );
      }
      if (delBtn) {
        delBtn.setAttribute(
          "aria-label",
          trimmed ? `Delete ${trimmed} API key` : "Delete API key row"
        );
      }
    }

    function addRow(key = "", value = "") {
      markDirty();
      const emptyState = document.getElementById("empty-state");
      if (emptyState) emptyState.remove();
      const list = document.getElementById("apikeys-list");
      if (!list) {
        console.warn("api_keys_page: #apikeys-list not found in DOM");
        return;
      }
      _rowCounter += 1;
      const suffix = `new-${_rowCounter}`;
      const row = document.createElement("div");
      row.className = "apikey-row";
      row.dataset.existing = "false";
      const keyInput = document.createElement("input");
      keyInput.type = "text";
      keyInput.className = "apikey-key";
      keyInput.value = key;
      keyInput.placeholder = "KEY_NAME";
      keyInput.id = `apikey-name-${suffix}`;
      keyInput.name = `apikey-name-${suffix}`;
      keyInput.setAttribute("aria-label", "API key name");
      const valInput = document.createElement("input");
      valInput.type = "password";
      valInput.className = "apikey-value";
      valInput.value = value;
      valInput.placeholder = "Enter value";
      valInput.id = `apikey-value-${suffix}`;
      valInput.name = `apikey-value-${suffix}`;
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn-delete";
      delBtn.dataset.apiAction = "delete-row";
      delBtn.title = "Delete";
      delBtn.textContent = "\u00d7";
      row.appendChild(keyInput);
      row.appendChild(valInput);
      row.appendChild(delBtn);
      // Initialize aria-labels now; re-run on every keyInput change so the
      // label tracks the key name the user just typed.
      updateRowAriaLabels(row, key);
      keyInput.addEventListener("input", () =>
        updateRowAriaLabels(row, keyInput.value)
      );
      list.appendChild(row);
      (key ? row.querySelector(".apikey-value") : row.querySelector(".apikey-key")).focus();
    }

    function addPreset(button) {
      const key = button.dataset.key;
      if (!key) return;
      const existingRow = Array.from(document.querySelectorAll(".apikey-row")).find(
        (row) => row.querySelector(".apikey-key")?.value.trim() === key
      );
      if (existingRow) {
        const valueInput = existingRow.querySelector(".apikey-value");
        (valueInput || existingRow.querySelector(".apikey-key"))?.focus();
        showResponseModal("info", `${key} is already added.`);
        return;
      }
      addRow(key, "");
      button.style.display = "none";
    }

    function hideExistingPresets() {
      const existingKeys = new Set(
        Array.from(document.querySelectorAll(".apikey-key")).map((input) =>
          input.value.trim()
        )
      );
      document.querySelectorAll(".btn-preset").forEach((btn) => {
        if (existingKeys.has(btn.dataset.key)) {
          btn.style.display = "none";
        }
      });
    }

    function deleteRow(rowOrButton) {
      const row = rowOrButton.closest ? rowOrButton.closest(".apikey-row") : rowOrButton;
      const keyInput = row?.querySelector(".apikey-key");
      const deletedKey = keyInput ? keyInput.value.trim() : "";
      if (row?.dataset.existing === "true" && deletedKey) {
        if (!confirm(`Remove ${deletedKey}? Save to apply.`)) return;
      }
      markDirty();
      row?.remove();
      if (deletedKey) {
        const presetBtn = document.querySelector(
          `.btn-preset[data-key="${deletedKey}"]`
        );
        if (presetBtn) presetBtn.style.display = "";
      }
      const list = document.getElementById("apikeys-list");
      if (list && list.children.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.id = "empty-state";
        const iconWrap = document.createElement("div");
        iconWrap.className = "empty-state-icon";
        iconWrap.setAttribute("aria-hidden", "true");
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", "icon-image");
        svg.setAttribute("viewBox", "0 0 256 256");
        svg.setAttribute("fill", "none");
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", "52"); rect.setAttribute("y", "112");
        rect.setAttribute("width", "152"); rect.setAttribute("height", "108");
        rect.setAttribute("rx", "16"); rect.setAttribute("stroke", "currentColor");
        rect.setAttribute("stroke-width", "16");
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", "M84 112V76a44 44 0 0 1 88 0v36");
        path.setAttribute("stroke", "currentColor"); path.setAttribute("stroke-width", "16");
        path.setAttribute("stroke-linecap", "round"); path.setAttribute("stroke-linejoin", "round");
        svg.appendChild(rect);
        svg.appendChild(path);
        iconWrap.appendChild(svg);
        empty.appendChild(iconWrap);
        const p1 = document.createElement("p");
        p1.textContent = "No API keys configured yet.";
        const p2 = document.createElement("p");
        p2.textContent = "Add keys below to enable plugin features.";
        empty.appendChild(p1);
        empty.appendChild(p2);
        list.appendChild(empty);
      }
    }

    async function saveGenericKeys() {
      const rows = document.querySelectorAll(".apikey-row");
      const entries = [];
      let missingValue = false;
      rows.forEach((row) => {
        const key = row.querySelector(".apikey-key")?.value.trim();
        const value = row.querySelector(".apikey-value")?.value.trim();
        const isExisting = row.dataset.existing === "true";
        if (!key) return;
        if (isExisting) {
          if (value) {
            entries.push({ key, value });
          } else {
            entries.push({ key, value: null, keepExisting: true });
          }
        } else if (!value) {
          missingValue = true;
        } else {
          entries.push({ key, value });
        }
      });
      if (missingValue) {
        showResponseModal("failure", "Please enter a value for new API keys");
        return;
      }
      const saveBtn = document.getElementById("saveApiKeysBtn");
      if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "Saving\u2026"; }
      let savedOk = false;
      try {
        const response = await fetch(config.saveGenericUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entries }),
        });
        const result = await response.json();
        if (response.ok) {
          savedOk = true;
          showResponseModal("success", result.message);
          setTimeout(() => globalThis.location.reload(), 1000);
        } else {
          showResponseModal("failure", result.error);
        }
      } catch (error) {
        showResponseModal("failure", "Failed to save API keys");
      } finally {
        finalizeSaveButton(saveBtn, savedOk);
      }
    }

    function saveKeys() {
      if (!_isDirty) {
        showResponseModal("info", "No changes to save.");
        return;
      }
      if (config.mode === "managed") {
        return saveManagedKeys();
      }
      return saveGenericKeys();
    }

    function togglePasswordVisibility(button) {
      const inputId = button.dataset.toggleInput;
      const input = document.getElementById(inputId);
      if (!input) return;
      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      button.textContent = isPassword ? "\u25CF" : "\u25CB";
      button.setAttribute("aria-label", isPassword ? "Hide key" : "Show key");
    }

    function init() {
      if (config.mode === "generic") {
        hideExistingPresets();
      }
      // Add show/hide toggle buttons next to password inputs
      document.querySelectorAll('input[type="password"].form-input').forEach((input) => {
        if (!input.value) return; // Skip unconfigured providers (empty input has no key to reveal)
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "toggle-password-btn";
        toggle.dataset.toggleInput = input.id;
        toggle.dataset.apiAction = "toggle-password";
        toggle.textContent = "\u25CB";
        toggle.setAttribute("aria-label", "Show key");
        toggle.title = "Toggle visibility";
        input.parentElement.insertBefore(toggle, input.nextSibling);
      });
      const addBtn = document.getElementById("addApiKeyBtn");
      const saveBtn = document.getElementById("saveApiKeysBtn");
      // Save starts disabled until the user makes a change
      if (saveBtn) saveBtn.disabled = true;
      if (addBtn) {
        addBtn.addEventListener("click", () => addRow());
      } else if (config.mode === "generic") {
        console.warn("api_keys_page: #addApiKeyBtn not found in DOM");
      }
      if (saveBtn) {
        saveBtn.addEventListener("click", saveKeys);
      } else {
        console.warn("api_keys_page: #saveApiKeysBtn not found in DOM");
      }
      // Mark dirty on any input change within the page
      document.addEventListener("input", (event) => {
        if (
          event.target.closest(".api-keys-frame") &&
          (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA")
        ) {
          markDirty();
        }
      });
      document.addEventListener("click", (event) => {
        const actionEl = event.target.closest("[data-api-action]");
        if (!actionEl) return;
        const action = actionEl.dataset.apiAction;
        if (action === "add-row") {
          addRow();
        } else if (action === "delete-key") {
          deleteKey(actionEl.dataset.keyName);
        } else if (action === "delete-row") {
          deleteRow(actionEl);
        } else if (action === "add-preset") {
          addPreset(actionEl);
        } else if (action === "toggle-password") {
          togglePasswordVisibility(actionEl);
        } else if (action === "reveal-input") {
          revealInput(actionEl);
        }
      });
    }

    Object.assign(globalThis, {
      addPreset,
      addRow,
      deleteKey,
      deleteRow,
      saveKeys,
    });

    return { init };
  }

  globalThis.InkyPiApiKeysPage = { create: createApiKeysPage };

  // Self-initialise from data-* attributes on the page container so no
  // inline <script> is needed (CSP blocks inline JS in production).
  // The deferred script attribute ensures the DOM is ready when this runs.
  function autoInit() {
    const frame = document.querySelector(".api-keys-frame");
    if (!frame) return;
    const config = {
      deleteManagedUrl: frame.dataset.deleteManagedUrl || "",
      mode: frame.dataset.mode || "managed",
      saveGenericUrl: frame.dataset.saveGenericUrl || "",
      saveManagedUrl: frame.dataset.saveManagedUrl || "",
    };
    createApiKeysPage(config).init();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }
})();

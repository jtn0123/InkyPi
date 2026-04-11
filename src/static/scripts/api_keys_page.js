(function () {
  // Module-scoped DOM helpers for the delete button inside a managed API key
  // card. Hoisted out of `createApiKeysPage` because they don't close over any
  // state (SonarCloud javascript:S7721).
  function addDeleteButton(sectionId, keyName) {
    // The Delete button lives inside `.api-key-actions` (the input row), NOT
    // `.api-key-card-head` (which holds the label + status). Walk up to the
    // card and then into the actions container so new buttons land next to
    // the input rather than next to the status line.
    const card = document
      .getElementById(`${sectionId}-status`)
      ?.closest(".api-key-card");
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
      deleteButton.textContent = "Delete";
      actions.appendChild(deleteButton);
    }
  }

  function removeDeleteButton(sectionId) {
    const card = document
      .getElementById(`${sectionId}-status`)
      ?.closest(".api-key-card");
    card
      ?.querySelector(
        '.api-key-actions .delete-button[data-api-action="delete-key"]'
      )
      ?.remove();
  }

  function createApiKeysPage(config) {
    // Dirty-tracking state: true when any field has changed since last save/load.
    let _isDirty = false;

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

    function updateManagedSummary() {
      const configured = Array.from(document.querySelectorAll(".api-key-status")).filter(
        (node) => !/not configured/i.test(node.textContent || "")
      ).length;
      const configuredChip = document.getElementById("configuredCountSummary");
      const providerChip = document.getElementById("providerCountSummary");
      if (configuredChip) configuredChip.textContent = `${configured} configured`;
      if (providerChip && config.mode === "managed") providerChip.textContent = "6 providers";
    }

    function updateConfiguredStatus(updatedKeys) {
      updatedKeys.forEach((key) => {
        const mapping = {
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
        const entry = mapping[key];
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
          // Clear the input and update its placeholder so subsequent edits start from empty
          // rather than appending to the prior entry.
          inputElement.value = "";
          inputElement.placeholder = "(leave blank to keep current)";
          addDeleteButton(sectionId, key);
        }
      });
      updateManagedSummary();
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
      saveBtn.textContent = "Save";
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

    function updateDeletedStatus(keyName) {
      const mapping = {
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
      const entry = mapping[keyName];
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
        inputElement.placeholder = "Enter API key";
      }
      removeDeleteButton(sectionId);
      updateManagedSummary();
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
      const row = document.createElement("div");
      row.className = "apikey-row";
      row.dataset.existing = "false";
      const keyInput = document.createElement("input");
      keyInput.type = "text";
      keyInput.className = "apikey-key";
      keyInput.value = key;
      keyInput.placeholder = "KEY_NAME";
      const valInput = document.createElement("input");
      valInput.type = "text";
      valInput.className = "apikey-value";
      valInput.value = value;
      valInput.placeholder = "Enter value";
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn-delete";
      delBtn.dataset.apiAction = "delete-row";
      delBtn.title = "Delete";
      delBtn.setAttribute("aria-label", "Delete API key");
      delBtn.textContent = "\u00d7";
      row.appendChild(keyInput);
      row.appendChild(valInput);
      row.appendChild(delBtn);
      list.appendChild(row);
      (key ? row.querySelector(".apikey-value") : row.querySelector(".apikey-key")).focus();
    }

    function addPreset(button) {
      const key = button.dataset.key;
      if (!key) return;
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
      } else {
        updateManagedSummary();
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
        if (action === "delete-key") {
          deleteKey(actionEl.dataset.keyName);
        } else if (action === "delete-row") {
          deleteRow(actionEl);
        } else if (action === "add-preset") {
          addPreset(actionEl);
        } else if (action === "toggle-password") {
          togglePasswordVisibility(actionEl);
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
})();

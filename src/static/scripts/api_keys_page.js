(function () {
  function createApiKeysPage(config) {
    function updateManagedSummary() {
      const configured = Array.from(document.querySelectorAll(".api-key-status")).filter(
        (node) => !/not configured/i.test(node.textContent || "")
      ).length;
      const configuredChip = document.getElementById("configuredCountSummary");
      const providerChip = document.getElementById("providerCountSummary");
      if (configuredChip) configuredChip.textContent = `${configured} configured`;
      if (providerChip && config.mode === "managed") providerChip.textContent = "4 providers";
    }

    function clearField(inputId) {
      const input = document.getElementById(inputId);
      if (!input) return;
      input.value = "";
      input.focus();
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
        };
        const entry = mapping[key];
        if (!entry) return;
        const [statusId, inputId, sectionId] = entry;
        const statusElement = document.getElementById(statusId);
        const inputElement = document.getElementById(inputId);
        const value = inputElement ? inputElement.value : "";
        if (statusElement && value && value !== config.maskPlaceholder) {
          statusElement.textContent = "";
          const strong1 = document.createElement("strong");
          strong1.textContent = "Status:";
          statusElement.appendChild(strong1);
          statusElement.appendChild(document.createTextNode(` Configured (${config.maskPlaceholder})`));
          inputElement.value = config.maskPlaceholder;
          addDeleteAndClearButtons(sectionId, key);
        } else if (statusElement && value === "") {
          statusElement.textContent = "";
          const strong2 = document.createElement("strong");
          strong2.textContent = "Status:";
          statusElement.appendChild(strong2);
          statusElement.appendChild(document.createTextNode(" Not configured"));
          removeDeleteAndClearButtons(sectionId);
        }
      });
      updateManagedSummary();
    }

    function addDeleteAndClearButtons(sectionId, keyName) {
      const formGroup = document.querySelector(`#${sectionId}-status`)?.parentElement;
      const inputContainer = formGroup?.querySelector(".input-container");
      if (!formGroup || !inputContainer) return;
      if (!inputContainer.querySelector(".clear-button")) {
        const clearButton = document.createElement("button");
        clearButton.type = "button";
        clearButton.className = "clear-button";
        clearButton.dataset.apiAction = "clear-field";
        clearButton.dataset.inputId = `${sectionId}-input`;
        clearButton.textContent = "×";
        inputContainer.appendChild(clearButton);
      }
      if (!formGroup.querySelector(".delete-button")) {
        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "header-button delete-button delete-button-danger";
        deleteButton.dataset.apiAction = "delete-key";
        deleteButton.dataset.keyName = keyName;
        deleteButton.textContent = "Delete";
        formGroup.appendChild(deleteButton);
      }
    }

    function removeDeleteAndClearButtons(sectionId) {
      const formGroup = document.querySelector(`#${sectionId}-status`)?.parentElement;
      const inputContainer = formGroup?.querySelector(".input-container");
      inputContainer?.querySelector(".clear-button")?.remove();
      formGroup?.querySelector(".delete-button")?.remove();
    }

    async function saveManagedKeys() {
      const form = document.getElementById("apiKeysForm");
      const saveBtn = document.getElementById("saveApiKeysBtn");
      if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "Saving\u2026"; }
      const data = new FormData(form);
      try {
        const resp = await fetch(config.saveManagedUrl, {
          method: "POST",
          body: data,
        });
        const result = await resp.json();
        if (resp.ok) {
          showResponseModal("success", `Success! ${result.message}`);
          if (result.updated && result.updated.length > 0) {
            updateConfiguredStatus(result.updated);
          }
        } else {
          showResponseModal("failure", `Error! ${result.error}`);
        }
      } catch (e) {
        showResponseModal("failure", "Failed to save keys. Please try again.");
      } finally {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = "Save"; }
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
      if (inputElement) inputElement.value = "";
      removeDeleteAndClearButtons(sectionId);
      updateManagedSummary();
    }

    function addRow(key = "", value = "") {
      const emptyState = document.getElementById("empty-state");
      if (emptyState) emptyState.remove();
      const list = document.getElementById("apikeys-list");
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
          entries.push({ key, value: null, keepExisting: true });
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
      try {
        const response = await fetch(config.saveGenericUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entries }),
        });
        const result = await response.json();
        if (response.ok) {
          showResponseModal("success", result.message);
          setTimeout(() => window.location.reload(), 1000);
        } else {
          showResponseModal("failure", result.error);
        }
      } catch (error) {
        showResponseModal("failure", "Failed to save API keys");
      } finally {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = "Save"; }
      }
    }

    function saveKeys() {
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
      document.getElementById("addApiKeyBtn")?.addEventListener("click", () => addRow());
      document.getElementById("saveApiKeysBtn")?.addEventListener("click", saveKeys);
      document.addEventListener("click", (event) => {
        const actionEl = event.target.closest("[data-api-action]");
        if (!actionEl) return;
        const action = actionEl.dataset.apiAction;
        if (action === "clear-field") {
          clearField(actionEl.dataset.inputId);
        } else if (action === "delete-key") {
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

    Object.assign(window, {
      addPreset,
      addRow,
      clearField,
      deleteKey,
      deleteRow,
      saveKeys,
    });

    return { init };
  }

  window.InkyPiApiKeysPage = { create: createApiKeysPage };
})();

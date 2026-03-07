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
          statusElement.innerHTML = `<strong>Status:</strong> Configured (${config.maskPlaceholder})`;
          inputElement.value = config.maskPlaceholder;
          addDeleteAndClearButtons(sectionId, key);
        } else if (statusElement && value === "") {
          statusElement.innerHTML = "<strong>Status:</strong> Not configured";
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
      }
    }

    async function deleteKey(keyName) {
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
      if (statusElement) statusElement.innerHTML = "<strong>Status:</strong> Not configured";
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
      row.innerHTML = `
        <input type="text" class="apikey-key" value="${key}" placeholder="KEY_NAME">
        <input type="text" class="apikey-value" value="${value}" placeholder="Enter value">
        <button type="button" class="btn-delete" data-api-action="delete-row" title="Delete" aria-label="Delete API key">×</button>
      `;
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
      row?.remove();
      if (deletedKey) {
        const presetBtn = document.querySelector(
          `.btn-preset[data-key="${deletedKey}"]`
        );
        if (presetBtn) presetBtn.style.display = "";
      }
      const list = document.getElementById("apikeys-list");
      if (list && list.children.length === 0) {
        list.innerHTML = `
          <div class="empty-state" id="empty-state">
            <div class="empty-state-icon" aria-hidden="true">
              <svg class="icon-image" viewBox="0 0 256 256" fill="none">
                <rect x="52" y="112" width="152" height="108" rx="16" stroke="currentColor" stroke-width="16"></rect>
                <path d="M84 112V76a44 44 0 0 1 88 0v36" stroke="currentColor" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"></path>
              </svg>
            </div>
            <p>No API keys configured yet.</p>
            <p>Add keys below to enable plugin features.</p>
          </div>
        `;
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
      }
    }

    function saveKeys() {
      if (config.mode === "managed") {
        return saveManagedKeys();
      }
      return saveGenericKeys();
    }

    function init() {
      if (config.mode === "generic") {
        hideExistingPresets();
      } else {
        updateManagedSummary();
      }
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

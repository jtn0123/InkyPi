(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function isFormValid(form = document.querySelector(".settings-form")) {
    if (!form || typeof form.checkValidity !== "function") return true;
    return form.checkValidity();
  }

  function focusFirstInvalidField(form) {
    const firstInvalid = form?.querySelector(":invalid");
    if (firstInvalid && typeof firstInvalid.focus === "function") {
      firstInvalid.focus();
    }
  }

  function applyFieldLevelError(fs, result) {
    if (!fs || !result) return false;
    if (result.field_errors && typeof result.field_errors === "object") {
      fs.setFieldErrors(result.field_errors);
      return true;
    }
    if (
      result.code === "validation_error" &&
      result.details &&
      typeof result.details.field === "string"
    ) {
      fs.setFieldError(result.details.field, result.error);
      return true;
    }
    return false;
  }

  function updateSliderValue(slider) {
    const valueDisplay = document.getElementById(`${slider.id}-value`);
    if (valueDisplay) {
      valueDisplay.textContent = Number.parseFloat(slider.value).toFixed(1);
    }
  }

  async function submitSettingsForm({
    form,
    formData,
    fs,
    saveBtn,
    saveSettingsUrl,
    snapshotState,
    getFormSnapshot,
    restoreFormFromSnapshot,
    checkDirty,
  }) {
    try {
      const response = await fetch(saveSettingsUrl, {
        method: "POST",
        body: formData,
      });
      const result = await response.json();
      if (response.ok) {
        snapshotState.current = getFormSnapshot(form);
        if (saveBtn) saveBtn.disabled = true;
        showResponseModal("success", `Success! ${result.message}`);
        return;
      }

      const fieldLevelError = applyFieldLevelError(fs, result);
      showResponseModal("failure", `Error! ${result.error}`);
      if (!fieldLevelError) {
        restoreFormFromSnapshot(form, snapshotState.current);
      }
    } catch (error) {
      console.error("Settings save failed:", error);
      showResponseModal(
        "failure",
        "An error occurred while processing your request. Please try again."
      );
      checkDirty();
    }
  }

  function createFormModule({ config, state, shared }) {
    const { getFormSnapshot, restoreFormFromSnapshot } = shared;
    const snapshotState = { current: null };

    // Server caps the cycle interval at "less than 24 hours" — see
    // _validate_settings_form. Without a client-side `max`, users can type
    // 999999 hours, click Save, and only then learn the limit (ISSUE-009).
    // Bind `max` to whichever unit is currently selected so the failure
    // surfaces inline.
    function _maxIntervalForUnit(unit) {
      if (unit === "hour") return 23;
      // minutes (default): 23h59 = 1439, but the server interpretation is
      // "strictly less than 24 hours" so 1440 would be invalid; use 1439.
      return 1439;
    }

    function refreshIntervalMax() {
      const intervalInput = document.getElementById("interval");
      const unitSelect = document.getElementById("unit");
      if (!intervalInput || !unitSelect) return;
      intervalInput.max = String(_maxIntervalForUnit(unitSelect.value));
    }

    function populateIntervalFields() {
      const intervalInput = document.getElementById("interval");
      const unitSelect = document.getElementById("unit");
      const seconds = config.pluginCycleIntervalSeconds;
      if (!intervalInput || !unitSelect || seconds == null) return;
      const intervalInMinutes = Math.floor(seconds / 60);
      const intervalInHours = Math.floor(seconds / 3600);
      if (intervalInHours > 0) {
        intervalInput.value = String(intervalInHours);
        unitSelect.value = "hour";
      } else {
        intervalInput.value = String(Math.max(1, intervalInMinutes));
        unitSelect.value = "minute";
      }
      refreshIntervalMax();
    }

    function checkDirty() {
      const saveBtn = document.getElementById("saveSettingsBtn");
      if (!saveBtn || !snapshotState.current) return;
      const current = getFormSnapshot();
      let dirty = false;
      const allKeys = new Set([
        ...Object.keys(snapshotState.current),
        ...Object.keys(current),
      ]);
      for (const key of allKeys) {
        if (snapshotState.current[key] !== current[key]) {
          dirty = true;
          break;
        }
      }
      saveBtn.disabled = !(dirty && isFormValid());
    }

    async function appendGeoData(formData) {
      // Geolocation is strictly opt-in: only runs when the user explicitly
      // enables "attach geo" in device settings (state.attachGeo). The
      // browser still prompts the user for permission, and failure is
      // swallowed silently so it never blocks the settings save flow.
      if (!state.attachGeo || !navigator.geolocation) return;
      try {
        const pos = await new Promise((resolve, reject) =>
          navigator.geolocation.getCurrentPosition(resolve, reject, { // NOSONAR javascript:S5604 -- opt-in, gated by state.attachGeo above
            enableHighAccuracy: true,
            maximumAge: 60000,
            timeout: 4000,
          })
        );
        if (pos?.coords) {
          formData.set("deviceLat", String(pos.coords.latitude));
          formData.set("deviceLon", String(pos.coords.longitude));
        }
      } catch (e) {
        console.warn("Geolocation unavailable:", e.message || e);
      }
    }

    async function handleAction() {
      const form = document.querySelector(".settings-form");
      const saveBtn = document.getElementById("saveSettingsBtn");
      if (!form) return;

      if (!isFormValid(form)) {
        if (typeof form.reportValidity === "function") form.reportValidity();
        focusFirstInvalidField(form);
        return;
      }
      if (saveBtn?.disabled) {
        showResponseModal("success", "No changes to save.");
        return;
      }

      const fs =
        globalThis.FormState && form ? globalThis.FormState.attach(form) : null;
      if (fs) fs.clearErrors();

      const formData = new FormData(form);
      await appendGeoData(formData);

      const doSubmit = () =>
        submitSettingsForm({
          form,
          formData,
          fs,
          saveBtn,
          saveSettingsUrl: config.saveSettingsUrl,
          snapshotState,
          getFormSnapshot,
          restoreFormFromSnapshot,
          checkDirty,
        });

      if (fs) {
        await fs.run(doSubmit);
        return;
      }

      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving…";
      }
      try {
        await doSubmit();
      } finally {
        if (saveBtn?.textContent === "Saving…") {
          saveBtn.textContent = "Save";
        }
      }
    }

    function toggleUseDeviceLocation(cb) {
      state.attachGeo = !!cb?.checked;
    }

    function bind() {
      const saveBtn = document.getElementById("saveSettingsBtn");
      snapshotState.current = getFormSnapshot();
      if (saveBtn) saveBtn.disabled = true;

      const settingsForm = document.querySelector(".settings-form");
      if (settingsForm) {
        settingsForm.addEventListener("input", checkDirty);
        settingsForm.addEventListener("change", checkDirty);
      }

      saveBtn?.addEventListener("click", handleAction);
      document
        .getElementById("useDeviceLocation")
        ?.addEventListener("change", (event) => {
          toggleUseDeviceLocation(event.currentTarget);
        });
      // ISSUE-009: re-cap the plugin-cycle-interval field whenever the unit
      // changes, so the inline browser validation reflects the server's
      // "<24h" rule for the currently-selected unit.
      document
        .getElementById("unit")
        ?.addEventListener("change", refreshIntervalMax);
      for (const slider of document.querySelectorAll(".settings-slider")) {
        slider.addEventListener("input", () => updateSliderValue(slider));
      }
    }

    return {
      bind,
      checkDirty,
      handleAction,
      populateIntervalFields,
      toggleUseDeviceLocation,
      updateSliderValue,
    };
  }

  settingsModules.createFormModule = createFormModule;
})();

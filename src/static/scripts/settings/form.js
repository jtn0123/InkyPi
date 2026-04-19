(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function createFormModule({ config, state, shared }) {
    const { getFormSnapshot, restoreFormFromSnapshot } = shared;
    let formSnapshot = null;

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
    }

    function isFormValid() {
      const form = document.querySelector(".settings-form");
      if (!form || typeof form.checkValidity !== "function") return true;
      return form.checkValidity();
    }

    function checkDirty() {
      const saveBtn = document.getElementById("saveSettingsBtn");
      if (!saveBtn || !formSnapshot) return;
      const current = getFormSnapshot();
      let dirty = false;
      const allKeys = new Set([
        ...Object.keys(formSnapshot),
        ...Object.keys(current),
      ]);
      for (const key of allKeys) {
        if (formSnapshot[key] !== current[key]) {
          dirty = true;
          break;
        }
      }
      saveBtn.disabled = !(dirty && isFormValid());
    }

    async function appendGeoData(formData) {
      if (!state.attachGeo || !navigator.geolocation) return;
      try {
        const pos = await new Promise((resolve, reject) =>
          navigator.geolocation.getCurrentPosition(resolve, reject, {
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
      if (
        form &&
        typeof form.checkValidity === "function" &&
        !form.checkValidity()
      ) {
        if (typeof form.reportValidity === "function") form.reportValidity();
        const firstInvalid = form.querySelector(":invalid");
        if (firstInvalid && typeof firstInvalid.focus === "function") {
          firstInvalid.focus();
        }
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

      const doSubmit = async () => {
        try {
          const response = await fetch(config.saveSettingsUrl, {
            method: "POST",
            body: formData,
          });
          const result = await response.json();
          if (response.ok) {
            formSnapshot = getFormSnapshot(form);
            if (saveBtn) saveBtn.disabled = true;
            showResponseModal("success", `Success! ${result.message}`);
          } else {
            if (
              fs &&
              result &&
              result.field_errors &&
              typeof result.field_errors === "object"
            ) {
              fs.setFieldErrors(result.field_errors);
            }
            showResponseModal("failure", `Error! ${result.error}`);
            restoreFormFromSnapshot(form, formSnapshot);
          }
        } catch (error) {
          console.error("Settings save failed:", error);
          showResponseModal(
            "failure",
            "An error occurred while processing your request. Please try again."
          );
          checkDirty();
        }
      };

      if (fs) {
        await fs.run(doSubmit);
      } else {
        if (saveBtn) {
          saveBtn.disabled = true;
          saveBtn.textContent = "Saving\u2026";
        }
        try {
          await doSubmit();
        } finally {
          if (saveBtn?.textContent === "Saving\u2026") {
            saveBtn.textContent = "Save";
          }
        }
      }
    }

    function toggleUseDeviceLocation(cb) {
      state.attachGeo = !!cb?.checked;
    }

    function updateSliderValue(slider) {
      const valueDisplay = document.getElementById(`${slider.id}-value`);
      if (valueDisplay) {
        valueDisplay.textContent = Number.parseFloat(slider.value).toFixed(1);
      }
    }

    function bind() {
      const saveBtn = document.getElementById("saveSettingsBtn");
      formSnapshot = getFormSnapshot();
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

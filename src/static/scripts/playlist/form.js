(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

  function validatePlaylistName() {
    const input = document.getElementById("playlist_name");
    const error = document.getElementById("playlist-name-error");
    const name = (input.value || "").trim();
    if (!name) {
      input.setAttribute("aria-invalid", "true");
      if (error) error.textContent = "Playlist name is required";
      input.focus();
      return null;
    }
    if (name.length > 64) {
      input.setAttribute("aria-invalid", "true");
      if (error) error.textContent = "Name must be 64 characters or fewer";
      input.focus();
      return null;
    }
    if (!ns.constants.PLAYLIST_NAME_RE.test(name)) {
      input.setAttribute("aria-invalid", "true");
      if (error) error.textContent = ns.constants.PLAYLIST_NAME_ERROR;
      input.focus();
      return null;
    }
    input.setAttribute("aria-invalid", "false");
    if (error) error.textContent = "";
    return name;
  }

  function validateCycleMinutes() {
    const input = document.getElementById("cycle_minutes");
    const error = document.getElementById("cycle-minutes-error");
    if (!input) return true;
    const raw = (input.value || "").trim();
    if (!raw) {
      input.setAttribute("aria-invalid", "false");
      if (error) error.textContent = "";
      return true;
    }
    const value = Number.parseInt(raw, 10);
    if (Number.isNaN(value) || String(value) !== raw) {
      input.setAttribute("aria-invalid", "true");
      if (error) error.textContent = "Must be a whole number";
      input.focus();
      return false;
    }
    if (value < 1 || value > 1440) {
      input.setAttribute("aria-invalid", "true");
      if (error) error.textContent = "Must be between 1 and 1440";
      input.focus();
      return false;
    }
    input.setAttribute("aria-invalid", "false");
    if (error) error.textContent = "";
    return true;
  }

  function scheduleFormState() {
    const form = document.getElementById("scheduleForm");
    return global.FormState && form ? global.FormState.attach(form) : null;
  }

  function applyFieldErrorFromResponse(fs, result) {
    if (!fs || !result) return false;
    if (result.field_errors && typeof result.field_errors === "object") {
      fs.setFieldErrors(result.field_errors);
      return true;
    }
    const field = result.details?.field;
    if (!field) return false;
    const message = result.error || "Invalid value";
    fs.setFieldError(field, message);
    return true;
  }

  function handlePlaylistMutationSuccess(result) {
    ns.closeModal();
    if (result.warning) {
      sessionStorage.setItem(
        "storedMessage",
        JSON.stringify({ type: "warning", text: result.warning })
      );
    }
    location.reload();
  }

  async function runPlaylistMutation(fs, requestFactory) {
    try {
      const response = await requestFactory();
      const result = await handleJsonResponse(response);
      if (response.ok && result?.success) {
        handlePlaylistMutationSuccess(result);
      } else if (fs && result) {
        applyFieldErrorFromResponse(fs, result);
      }
    } catch (error) {
      console.error("Error:", error);
      showResponseModal(
        "failure",
        "An error occurred while processing your request."
      );
    }
  }

  async function createPlaylist() {
    const fs = scheduleFormState();
    if (fs) fs.clearErrors();
    const playlistName = validatePlaylistName();
    if (!playlistName) return;
    if (!validateCycleMinutes()) return;
    const startTime = document.getElementById("start_time").value;
    const endTime = document.getElementById("end_time").value;
    const cycleMinutes = document.getElementById("cycle_minutes")?.value || "";

    const submit = async () => {
      await runPlaylistMutation(fs, () =>
        fetch(ns.config.create_playlist_url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            playlist_name: playlistName,
            start_time: startTime,
            end_time: endTime,
            cycle_minutes: cycleMinutes || null,
          }),
        })
      );
    };

    if (fs) {
      await fs.run(submit);
    } else {
      await submit();
    }
  }

  async function updatePlaylist() {
    const fs = scheduleFormState();
    if (fs) fs.clearErrors();
    const oldName = document.getElementById("editingPlaylistName").value;
    const newName = validatePlaylistName();
    if (!newName) return;
    if (!validateCycleMinutes()) return;
    const startTime = document.getElementById("start_time").value;
    const endTime = document.getElementById("end_time").value;
    const cycleMinutes = document.getElementById("cycle_minutes").value;

    const submit = async () => {
      await runPlaylistMutation(fs, () =>
        fetch(
          ns.config.update_playlist_base_url + encodeURIComponent(oldName),
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              new_name: newName,
              start_time: startTime,
              end_time: endTime,
              cycle_minutes: cycleMinutes || null,
            }),
          }
        )
      );
    };

    if (fs) {
      await fs.run(submit);
    } else {
      await submit();
    }
  }

  async function deletePlaylist() {
    const name = document.getElementById("editingPlaylistName").value;
    try {
      const response = await fetch(
        ns.config.delete_playlist_base_url + encodeURIComponent(name),
        { method: "DELETE" }
      );
      const result = await handleJsonResponse(response);
      if (response.ok && result?.success) {
        ns.closeModal();
        location.reload();
      }
    } catch (error) {
      console.error("Error:", error);
      showResponseModal(
        "failure",
        "An error occurred while processing your request."
      );
    }
  }

  async function saveDeviceCycle() {
    const input = document.getElementById("device_cycle_minutes");
    const raw = (input?.value || "").trim();
    const minutes = Number.parseInt(raw, 10);
    if (!/^\d+$/.test(raw) || minutes < 1 || minutes > 1440) {
      showResponseModal("failure", "Enter minutes between 1 and 1440");
      return;
    }
    try {
      const response = await fetch(ns.config.update_device_cycle_url, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutes }),
      });
      const result = await handleJsonResponse(response);
      if (response.ok && result?.success) {
        ns.closeDeviceCycleModal();
        location.reload();
      }
    } catch (error) {
      console.debug("Failed saving playlist device cadence:", error);
      showResponseModal("failure", "Failed saving cadence");
    }
  }

  function initFormControls() {
    if (ns.runtime.formControlsBound) return;
    const newBtn = document.getElementById("newPlaylistBtn");
    if (newBtn) {
      newBtn.addEventListener("click", (event) =>
        ns.openCreateModal(event.currentTarget)
      );
    }

    const saveBtn = document.getElementById("saveButton");
    if (saveBtn) {
      saveBtn.addEventListener("click", () => {
        const mode =
          document.getElementById("playlistModal")?.dataset.mode || "create";
        if (mode === "edit") {
          updatePlaylist();
        } else {
          createPlaylist();
        }
      });
    }

    document
      .getElementById("deleteButton")
      ?.addEventListener("click", deletePlaylist);
    document
      .getElementById("saveRefreshSettingsBtn")
      ?.addEventListener("click", ns.saveRefreshSettings);
    document
      .getElementById("editDeviceCycleBtn")
      ?.addEventListener("click", ns.openDeviceCycleModal);

    ns.runtime.formControlsBound = true;
  }

  Object.assign(ns, {
    applyFieldErrorFromResponse,
    createPlaylist,
    deletePlaylist,
    handlePlaylistMutationSuccess,
    initFormControls,
    runPlaylistMutation,
    saveDeviceCycle,
    updatePlaylist,
  });

  global.applyFieldErrorFromResponse = applyFieldErrorFromResponse;
})(globalThis);

(function (global) {
  global.InkyPiPlaylist = global.InkyPiPlaylist || {};
  const ns = global.InkyPiPlaylist;

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

  function showPlaylistNameError(message) {
    const input = document.getElementById("playlist_name");
    const error = document.getElementById("playlist-name-error");
    if (!input) return;
    input.setAttribute("aria-invalid", "true");
    if (error) error.textContent = message;
    input.focus();
  }

  function bindPlaylistNameLengthGuard() {
    const input = document.getElementById("playlist_name");
    if (!input || input.dataset.lengthGuardBound === "true") return;
    input.dataset.lengthGuardBound = "true";
    input.addEventListener("beforeinput", (event) => {
      if (event.inputType !== "insertFromPaste") return;
      const max = Number.parseInt(input.getAttribute("maxlength") || "0", 10);
      if (!max || !event.data) return;
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? input.value.length;
      const nextLength = input.value.length - Math.max(0, end - start) + event.data.length;
      if (nextLength <= max) return;
      event.preventDefault();
      showPlaylistNameError("Name must be 64 characters or fewer");
    });
    input.addEventListener("input", () => {
      const error = document.getElementById("playlist-name-error");
      const max = Number.parseInt(input.getAttribute("maxlength") || "0", 10);
      if (
        error?.textContent === "Name must be 64 characters or fewer" &&
        (input.value || "").length <= (max || 64)
      ) {
        input.setAttribute("aria-invalid", "false");
        error.textContent = "";
      }
    });
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

  // The page reloads to show the saved playlist, and the server's message is
  // shown after the reload. A warning (the new hours overlap Default's) goes
  // in the same toast, so it isn't lost behind the success message.
  function handlePlaylistMutationSuccess(result) {
    ns.closeModal();
    const message = result?.message || "Saved playlist.";
    if (result?.warning) {
      ns.reloadWithMessage("warning", `${message} ${result.warning}`);
      return;
    }
    ns.reloadWithMessage("success", message);
  }

  // The Save button shows its busy state for as long as this runs (the
  // callers wrap it in FormState.run). A refusal names the field when the
  // server says which one, and is toasted either way.
  async function runPlaylistMutation(fs, url, init) {
    let result;
    try {
      result = await fetchJson(url, init);
    } catch (error) {
      // Shown in the toast below, so it isn't logged as an error.
      console.debug("Playlist save failed:", error);
      applyFieldErrorFromResponse(fs, error?.data);
      showResponseModal(
        "failure",
        `Failed to save playlist: ${globalThis.InkyPiHttp.errorMessage(error)}`
      );
      return;
    }
    handlePlaylistMutationSuccess(result);
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

    const submit = () =>
      runPlaylistMutation(fs, ns.config.create_playlist_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          playlist_name: playlistName,
          start_time: startTime,
          end_time: endTime,
          cycle_minutes: cycleMinutes || null,
        }),
      });

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
    const endInput = document.getElementById("end_time");
    const originalEndTime =
      document.getElementById("playlistModal")?.dataset.originalEndTime || "";
    const endTime =
      originalEndTime === "24:00" && endInput.value === "23:59"
        ? "24:00"
        : endInput.value;
    const cycleMinutes = document.getElementById("cycle_minutes").value;

    const submit = () =>
      runPlaylistMutation(
        fs,
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
      );

    if (fs) {
      await fs.run(submit);
    } else {
      await submit();
    }
  }

  // The edit dialog's Delete asks first, like the card's Delete: it closes
  // the edit dialog and opens the same confirm dialog for this playlist.
  function confirmDeletePlaylist() {
    const name = document.getElementById("editingPlaylistName").value;
    ns.closeModal();
    // Closing hands focus back to the card's Edit button, so the confirm
    // dialog returns focus there too.
    ns.openDeletePlaylistModal(name, document.activeElement);
  }

  // Only a bug in this page gets here: request failures are handled above.
  function reportPlaylistSaveFailure(error) {
    console.error("Failed to save playlist:", error);
    showResponseModal(
      "failure",
      `Failed to save playlist: ${globalThis.InkyPiHttp.errorMessage(error)}`
    );
  }

  function initFormControls() {
    if (ns.runtime.formControlsBound) return;
    bindPlaylistNameLengthGuard();
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
          updatePlaylist().catch(reportPlaylistSaveFailure);
        } else {
          createPlaylist().catch(reportPlaylistSaveFailure);
        }
      });
    }

    document
      .getElementById("deleteButton")
      ?.addEventListener("click", confirmDeletePlaylist);
    document
      .getElementById("saveRefreshSettingsBtn")
      ?.addEventListener("click", ns.saveRefreshSettings);

    ns.runtime.formControlsBound = true;
  }

  Object.assign(ns, {
    applyFieldErrorFromResponse,
    createPlaylist,
    handlePlaylistMutationSuccess,
    initFormControls,
    runPlaylistMutation,
    updatePlaylist,
  });

  global.applyFieldErrorFromResponse = applyFieldErrorFromResponse;
})(globalThis);

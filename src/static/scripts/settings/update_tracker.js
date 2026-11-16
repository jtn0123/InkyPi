// Follows an update or rollback from start to finish on the Settings page.
//
// A run is tracked however it started: from this page's buttons, from the
// sidebar's quick update (the "inkypi:update-started" event), or before the
// page loaded (resume() finds it running). Every real update stops and
// restarts InkyPi, so failed polls are expected: the tracker says
// "Restarting…" and keeps asking, less often, until the device answers.
// When /settings/update_status says the run is over, it says how it ended,
// using the .last-update-failure record for the reason.
(function () {
  globalThis.InkyPiSettingsModules = globalThis.InkyPiSettingsModules || {};
  const settingsModules = globalThis.InkyPiSettingsModules;

  const POLL_MS = 2000;
  // Waits after each failed poll in a row; the last one repeats.
  const RETRY_DELAYS_MS = [2000, 3000, 5000, 8000, 13000, 15000];
  // After this long without an answer, warn that the device may be stuck.
  const SLOW_RESTART_MS = 10 * 60 * 1000;
  // A proxy in front of InkyPi answers these while the service is down.
  const RESTART_STATUSES = new Set([502, 503, 504]);

  const WORDS = {
    update: { label: "Update", noun: "update", verb: "Updating" },
    rollback: { label: "Rollback", noun: "rollback", verb: "Rolling back" },
  };

  function wordsFor(kind) {
    return WORDS[kind] || WORDS.update;
  }

  // Identifies one failure record: a later run that fails writes a new one.
  function failureStamp(lastFailure) {
    if (!lastFailure) return "";
    return JSON.stringify([
      lastFailure.timestamp ?? null,
      lastFailure.exit_code ?? null,
      lastFailure.last_command ?? null,
      !!lastFailure.parse_error,
    ]);
  }

  function failureReason(lastFailure) {
    if (lastFailure.parse_error) return "";
    const parts = [];
    if (lastFailure.last_command) parts.push(`at step: ${lastFailure.last_command}`);
    if (typeof lastFailure.exit_code === "number") {
      parts.push(`(exit ${lastFailure.exit_code})`);
    }
    return parts.join(" ");
  }

  // How a finished run ended: "success", "failure" or "unknown" (the run
  // left the failure record as it found it, so it recorded no result).
  function describeOutcome(kind, lastFailure, failureBefore) {
    const { label } = wordsFor(kind);
    if (!lastFailure) {
      return { state: "success", text: `${label} finished.` };
    }
    if (failureStamp(lastFailure) === failureBefore) {
      return {
        state: "unknown",
        text: `${label} finished without recording a result. Check the Logs panel.`,
      };
    }
    if (lastFailure.parse_error) {
      return {
        state: "failure",
        text: `${label} failed, and its failure record couldn't be read.`,
      };
    }
    const reason = failureReason(lastFailure);
    return {
      state: "failure",
      text: `${label} failed${reason ? ` ${reason}` : ""}. The details are below.`,
    };
  }

  function retryDelay(misses) {
    return RETRY_DELAYS_MS[Math.min(misses, RETRY_DELAYS_MS.length) - 1];
  }

  function isRestartError(error) {
    return (
      error?.kind === "network" ||
      (error?.kind === "http" && RESTART_STATUSES.has(error.status))
    );
  }

  function createUpdateTrackerModule({ config, shared, logs, onFinished }) {
    const { renderUpdateFailureBanner } = shared;
    // The run being followed, or null.
    let run = null;
    // The last /settings/update_status reply, for the failure seen before
    // a run this page starts.
    let lastStatus = null;
    let updateBtnWasDisabled = null;

    function renderStatus(data) {
      renderUpdateFailureBanner(
        data?.last_failure ?? null,
        data?.prev_version ?? null,
        !!data?.rollback_eligible
      );
    }

    function showProgress(state, text, { reload = false } = {}) {
      const box = document.getElementById("updateProgress");
      if (!box) return;
      box.hidden = false;
      box.dataset.state = state;
      const textEl = document.getElementById("updateProgressText");
      if (textEl) textEl.textContent = text;
      const reloadBtn = document.getElementById("updateReloadBtn");
      if (reloadBtn) reloadBtn.hidden = !reload;
    }

    // While a run is going (or a start request is out), Update now and
    // Roll back are disabled. Update now gets back the state it had; the
    // version check that follows a finished run sets it again.
    function setBusy(busy) {
      const panel = document.getElementById("updatePanel");
      const wasBusy = panel?.getAttribute("aria-busy") === "true";
      panel?.setAttribute("aria-busy", busy ? "true" : "false");
      const updateBtn = document.getElementById("startUpdateBtn");
      if (updateBtn && busy && !wasBusy) {
        updateBtnWasDisabled = updateBtn.disabled;
        updateBtn.disabled = true;
      } else if (updateBtn && !busy && wasBusy && updateBtnWasDisabled !== null) {
        updateBtn.disabled = updateBtnWasDisabled;
      }
      for (const id of ["rollbackUpdateBtn", "confirmRollbackBtn"]) {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = busy;
      }
    }

    function schedule(delay) {
      if (!run) return;
      clearTimeout(run.timer);
      run.timer = setTimeout(poll, delay);
    }

    function begin(kind, lastFailureBefore) {
      if (run) {
        if (kind) run.kind = kind;
        return;
      }
      run = {
        kind: kind || "update",
        failureBefore: failureStamp(lastFailureBefore),
        timer: null,
        misses: 0,
        unreachableSince: null,
        sawRestart: false,
      };
      setBusy(true);
      const { verb } = wordsFor(run.kind);
      showProgress(
        "running",
        `${verb}… InkyPi restarts part-way through; this page keeps checking until it finishes.`
      );
      schedule(POLL_MS);
    }

    function onPollFailed(error) {
      run.misses += 1;
      run.unreachableSince = run.unreachableSince ?? Date.now();
      if (isRestartError(error)) {
        run.sawRestart = true;
        const waited = Date.now() - run.unreachableSince;
        const minutes = Math.round(waited / 60000);
        const { noun } = wordsFor(run.kind);
        showProgress(
          "running",
          waited > SLOW_RESTART_MS
            ? `InkyPi hasn't come back after ${minutes} minutes. A failed ${noun} can leave it stopped, so check the device. Still checking…`
            : "Restarting… waiting for InkyPi to come back."
        );
      } else {
        const message = globalThis.InkyPiHttp.errorMessage(
          error,
          "Couldn't read the update status."
        );
        showProgress("running", `${message} Retrying…`);
      }
      // The progress line already shows this failure.
      console.debug("Update status poll failed; retrying:", error);
      schedule(retryDelay(run.misses));
    }

    async function finishRun(data) {
      const finished = run;
      clearTimeout(finished.timer);
      run = null;
      setBusy(false);
      const outcome = describeOutcome(
        finished.kind,
        data?.last_failure ?? null,
        finished.failureBefore
      );
      showProgress(outcome.state, outcome.text, { reload: true });
      void logs.fetchAndRenderLogs();
      const version = await onFinished?.();
      if (outcome.state === "success" && version?.current) {
        const current = String(version.current);
        const installed = document.getElementById("currentVersion");
        if (installed) installed.textContent = current;
        showProgress(
          "success",
          `${outcome.text} InkyPi is now running v${current.replace(/^v/, "")}.`,
          { reload: true }
        );
      }
    }

    function onStatus(data) {
      lastStatus = data;
      run.misses = 0;
      run.unreachableSince = null;
      renderStatus(data);
      if (!data?.running) {
        void finishRun(data);
        return;
      }
      if (data.kind) run.kind = data.kind;
      const { verb } = wordsFor(run.kind);
      showProgress(
        "running",
        run.sawRestart
          ? "InkyPi is back and is checking the new version…"
          : `${verb}… InkyPi restarts part-way through; this page keeps checking until it finishes.`
      );
      void logs.fetchAndRenderLogs();
      schedule(POLL_MS);
    }

    async function poll() {
      const current = run;
      if (!current) return;
      let data;
      try {
        data = await fetchJson(config.updateStatusUrl, { cache: "no-store" });
      } catch (e) {
        if (run === current) onPollFailed(e);
        return;
      }
      if (run === current) onStatus(data);
    }

    // Read the status once (page load, or after a refused start) and follow
    // a run that is already going. A paused run is picked up again.
    async function resume() {
      if (run) {
        schedule(0);
        return;
      }
      let data;
      try {
        data = await fetchJson(config.updateStatusUrl, { cache: "no-store" });
      } catch (e) {
        // An error reply leaves the banner as it was, as it always has.
        if (e?.kind !== "http") console.warn("Update status refresh failed:", e);
        return;
      }
      lastStatus = data;
      renderStatus(data);
      if (data?.running && !run) begin(data.kind, data.last_failure ?? null);
    }

    // A start request this page just made was accepted.
    function track(kind) {
      begin(kind, lastStatus?.last_failure ?? null);
    }

    // Stop polling while the page is hidden (pagehide). The run is kept, so
    // a page restored from the back/forward cache carries on in resume().
    function pause() {
      if (run) clearTimeout(run.timer);
    }

    function bind() {
      document
        .getElementById("updateReloadBtn")
        ?.addEventListener("click", () => globalThis.location.reload());
      // The sidebar's quick update, started while this page is open.
      document.addEventListener("inkypi:update-started", (event) =>
        track(event.detail?.kind || "update")
      );
    }

    return { bind, pause, resume, setBusy, track };
  }

  settingsModules.createUpdateTrackerModule = createUpdateTrackerModule;
  settingsModules.describeUpdateOutcome = describeOutcome;
})();

(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

  function parseJsonValue(rawValue, label) {
    if (!rawValue) return null;
    try {
      return JSON.parse(rawValue);
    } catch (error) {
      console.debug("Failed parsing playlist progress payload:", label, error);
      return null;
    }
  }

  async function readResponseJson(response, label) {
    try {
      return await response.json();
    } catch (error) {
      console.debug("Failed parsing playlist progress response:", label, error);
      return null;
    }
  }

  function formatElapsed(ms) {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    if (minutes > 0) return `${minutes}m ${remainder}s`;
    return `${seconds}s`;
  }

  function stripLeadingTime(value) {
    return value.replace(/^\s*\d{1,2}:\d{2}(?::\d{2})?\s*(AM|PM)?\s*/i, "");
  }

  function restoreStoredMessage() {
    const storedMessage = sessionStorage.getItem("storedMessage");
    if (!storedMessage) return;
    try {
      const { type, text } = JSON.parse(storedMessage);
      showResponseModal(type, text);
    } catch (error) {
      console.debug("Invalid playlist stored message payload:", error);
    }
    sessionStorage.removeItem("storedMessage");
  }

  function bindStoredMessageHandler() {
    if (ns.runtime.storedMessageBound) return;
    ns.runtime.storedMessageBound = true;
    if (document.readyState === "complete") {
      restoreStoredMessage();
      return;
    }
    global.addEventListener("load", restoreStoredMessage, { once: true });
  }

  function findLatestPlaylistProgress() {
    let lastMatch = null;
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (!key?.startsWith("INKYPI_LAST_PROGRESS:playlist:")) continue;
      const parsed = parseJsonValue(localStorage.getItem(key), key);
      if (parsed) lastMatch = parsed;
    }
    return (
      lastMatch ||
      parseJsonValue(
        localStorage.getItem("INKYPI_LAST_PROGRESS"),
        "INKYPI_LAST_PROGRESS"
      )
    );
  }

  function renderStoredProgressLines(list, data) {
    if (!list) return;
    list.innerHTML = "";
    const lines = Array.isArray(data.lines) ? data.lines : [];
    const timestamp = new Date(data.finishedAtIso).toLocaleTimeString();
    lines.forEach((line) => {
      const li = document.createElement("li");
      const ts = document.createElement("time");
      ts.textContent = timestamp;
      li.appendChild(ts);
      li.appendChild(
        document.createTextNode(` ${stripLeadingTime(String(line))}`)
      );
      list.appendChild(li);
    });
  }

  function showLastProgressGlobal() {
    const data = findLatestPlaylistProgress();
    if (!data) {
      showResponseModal("failure", "No recent progress to show");
      return;
    }

    const progress = document.getElementById("globalProgress");
    const textEl = document.getElementById("globalProgressText");
    const clockEl = document.getElementById("globalProgressClock");
    const elapsedEl = document.getElementById("globalProgressElapsed");
    const list = document.getElementById("globalProgressList");
    const bar = document.getElementById("globalProgressBar");
    const finishedAt = new Date(data.finishedAtIso);
    const finishedClock = Number.isNaN(finishedAt.getTime())
      ? ""
      : finishedAt.toLocaleTimeString();

    renderStoredProgressLines(list, data);
    if (textEl) textEl.textContent = data.summary || "Last run";
    if (clockEl) clockEl.textContent = finishedClock;
    if (elapsedEl) elapsedEl.textContent = "-";
    if (bar) {
      bar.style.width = "100%";
      bar.setAttribute("aria-valuenow", 100);
    }
    if (progress) progress.style.display = "block";
  }

  function getProgressElements(pluginInstance) {
    return {
      loadingIndicator: document
        .getElementById(pluginInstance)
        ?.querySelector(".loading-indicator"),
      progress: document.getElementById("globalProgress"),
      progressBar: document.getElementById("globalProgressBar"),
      progressClock: document.getElementById("globalProgressClock"),
      progressElapsed: document.getElementById("globalProgressElapsed"),
      progressList: document.getElementById("globalProgressList"),
      progressText: document.getElementById("globalProgressText"),
    };
  }

  function updateProgressBar(progressBar, pct) {
    if (!progressBar || typeof pct !== "number") return;
    progressBar.style.width = `${pct}%`;
    progressBar.setAttribute("aria-valuenow", pct);
  }

  function appendProgressLog(progressList, line) {
    if (!progressList) return;
    const li = document.createElement("li");
    const ts = document.createElement("time");
    ts.dateTime = new Date().toISOString();
    ts.textContent = new Date().toLocaleTimeString();
    li.appendChild(ts);
    li.appendChild(document.createTextNode(` ${stripLeadingTime(line)}`));
    progressList.appendChild(li);
    progressList.scrollTop = progressList.scrollHeight;
  }

  function createProgressTracker(elements, startedAt) {
    let clockTimer = null;

    function tickClock() {
      if (elements.progressClock) {
        elements.progressClock.textContent = new Date().toLocaleTimeString();
      }
      if (elements.progressElapsed) {
        elements.progressElapsed.textContent = formatElapsed(Date.now() - startedAt);
      }
    }

    function setStep(text, pct) {
      if (elements.progress) elements.progress.style.display = "block";
      if (elements.progressText) elements.progressText.textContent = text;
      updateProgressBar(elements.progressBar, pct);
      appendProgressLog(elements.progressList, text);
    }

    return {
      start() {
        if (elements.progressList) elements.progressList.innerHTML = "";
        if (elements.progressElapsed) elements.progressElapsed.textContent = "0s";
        if (elements.progressClock) {
          elements.progressClock.textContent = new Date().toLocaleTimeString();
        }
        updateProgressBar(elements.progressBar, 10);
        tickClock();
        clockTimer = global.setInterval(tickClock, 1000);
        setStep("Preparing...", 10);
      },
      stop() {
        if (clockTimer) {
          global.clearInterval(clockTimer);
          clockTimer = null;
        }
      },
      setStep,
      setSummary(text) {
        if (elements.progressText) elements.progressText.textContent = text;
        appendProgressLog(elements.progressList, text);
      },
      snapshot(ctx) {
        return {
          ctx,
          finishedAtIso: new Date().toISOString(),
          lines: Array.from(
            elements.progressList?.querySelectorAll("li") || [],
            (li) => li.textContent || ""
          ),
          summary: elements.progressText?.textContent || "Done",
        };
      },
    };
  }

  function setButtonLoadingState(btnEl, loading) {
    if (!btnEl) return;
    btnEl.disabled = loading;
    const spinner = btnEl.querySelector(".btn-spinner");
    if (spinner) spinner.style.display = loading ? "inline-block" : "none";
  }

  async function playMetricSteps(tracker, metrics) {
    if (!Array.isArray(metrics.steps) || !metrics.steps.length) return;
    let pct = 60;
    const increment = 30 / metrics.steps.length;
    for (const [name, ms] of metrics.steps) {
      pct += increment;
      tracker.setStep(`${name} ${ms} ms`, pct);
      await new Promise((resolve) => global.setTimeout(resolve, 50));
    }
  }

  function buildMetricsSummary(metrics) {
    const parts = [];
    const addMetric = (label, value) => {
      if (value !== null && value !== undefined) {
        parts.push(`${label} ${value} ms`);
      }
    };

    addMetric("Request", metrics.request_ms);
    addMetric("Generate", metrics.generate_ms);
    addMetric("Preprocess", metrics.preprocess_ms);
    addMetric("Display", metrics.display_ms);

    return parts.join(" • ");
  }

  function persistProgressSnapshot(tracker, ctx) {
    const data = tracker.snapshot(ctx);
    const key = ns.buildProgressKey(data.ctx);
    localStorage.setItem(key, JSON.stringify(data));
    localStorage.setItem("INKYPI_LAST_PROGRESS", JSON.stringify(data));
  }

  async function handlePluginDisplaySuccess(response, tracker) {
    tracker.setStep("Waiting (device)...", 60);
    const result = await readResponseJson(response, "playlist display response");
    if (!(response.ok && result?.success)) {
      showResponseModal(
        "failure",
        result?.error || result?.message || "Display request failed"
      );
      tracker.setStep("Failed", 100);
      return false;
    }

    const metrics = result.metrics || {};
    await playMetricSteps(tracker, metrics);
    const summary = buildMetricsSummary(metrics);
    if (summary) tracker.setSummary(summary);
    tracker.setStep("Display updating...", 90);
    sessionStorage.setItem(
      "storedMessage",
      JSON.stringify({ type: "success", text: `Success! ${result.message}` })
    );
    location.reload();
    return true;
  }

  async function displayPluginInstance(
    playlistName,
    pluginId,
    pluginInstance,
    btnEl
  ) {
    const elements = getProgressElements(pluginInstance);
    const tracker = createProgressTracker(elements, Date.now());
    const ctx = {
      page: "playlist",
      playlist: playlistName,
      pluginId,
      instance: pluginInstance,
    };

    if (elements.loadingIndicator) elements.loadingIndicator.style.display = "block";
    setButtonLoadingState(btnEl, true);
    tracker.start();
    let completedSuccessfully = false;

    try {
      const response = await fetch(ns.config.display_plugin_instance_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          playlist_name: playlistName,
          plugin_id: pluginId,
          plugin_instance: pluginInstance,
        }),
      });
      completedSuccessfully = await handlePluginDisplaySuccess(response, tracker);
    } catch (error) {
      console.error("Error:", error);
      showResponseModal(
        "failure",
        "An error occurred while processing your request."
      );
      tracker.setStep("Failed", 100);
    } finally {
      if (elements.loadingIndicator) elements.loadingIndicator.style.display = "none";
      setButtonLoadingState(btnEl, false);
      if (completedSuccessfully) tracker.setStep("Done", 100);
      tracker.stop();
      persistProgressSnapshot(tracker, ctx);
      global.setTimeout(() => {
        if (elements.progress) elements.progress.style.display = "none";
      }, ns.constants.PROGRESS_HIDE_DELAY_MS);
    }
  }

  ns.bindStoredMessageHandler = bindStoredMessageHandler;
  ns.displayPluginInstance = displayPluginInstance;
  ns.restoreStoredMessage = restoreStoredMessage;
  ns.showLastProgressGlobal = showLastProgressGlobal;
})(globalThis);

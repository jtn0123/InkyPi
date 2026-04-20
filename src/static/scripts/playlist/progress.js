(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

  function restoreStoredMessage() {
    const storedMessage = sessionStorage.getItem("storedMessage");
    if (!storedMessage) return;
    try {
      const { type, text } = JSON.parse(storedMessage);
      showResponseModal(type, text);
    } catch (_err) {}
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

  function showLastProgressGlobal() {
    try {
      let data = null;
      for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i);
        if (!key || !key.startsWith("INKYPI_LAST_PROGRESS:playlist:")) continue;
        try {
          data = JSON.parse(localStorage.getItem(key));
        } catch (_err) {}
      }
      if (!data) {
        const raw = localStorage.getItem("INKYPI_LAST_PROGRESS");
        if (raw) data = JSON.parse(raw);
      }
      if (!data) {
        try {
          showResponseModal("failure", "No recent progress to show");
        } catch (_err) {}
        return;
      }

      const progress = document.getElementById("globalProgress");
      const textEl = document.getElementById("globalProgressText");
      const clockEl = document.getElementById("globalProgressClock");
      const elapsedEl = document.getElementById("globalProgressElapsed");
      const list = document.getElementById("globalProgressList");
      const bar = document.getElementById("globalProgressBar");

      if (list) {
        list.innerHTML = "";
        data.lines.forEach((line) => {
          const li = document.createElement("li");
          const ts = document.createElement("time");
          ts.textContent = new Date(data.finishedAtIso).toLocaleTimeString();
          li.appendChild(ts);
          li.appendChild(document.createTextNode(line));
          list.appendChild(li);
        });
      }
      if (textEl) textEl.textContent = data.summary || "Last run";
      if (clockEl) {
        clockEl.textContent = new Date(data.finishedAtIso).toLocaleTimeString();
      }
      if (elapsedEl) elapsedEl.textContent = "—";
      if (bar) bar.style.width = "100%";
      if (progress) progress.style.display = "block";
    } catch (_err) {}
  }

  async function displayPluginInstance(
    playlistName,
    pluginId,
    pluginInstance,
    btnEl
  ) {
    const loadingIndicator = document
      .getElementById(pluginInstance)
      ?.querySelector(".loading-indicator");
    const progress = document.getElementById("globalProgress");
    const progressText = document.getElementById("globalProgressText");
    const progressBar = document.getElementById("globalProgressBar");
    const progressClock = document.getElementById("globalProgressClock");
    const progressElapsed = document.getElementById("globalProgressElapsed");
    const progressList = document.getElementById("globalProgressList");
    const startedAt = Date.now();
    let clockTimer = null;

    function formatElapsed(ms) {
      const seconds = Math.floor(ms / 1000);
      const minutes = Math.floor(seconds / 60);
      const remainder = seconds % 60;
      if (minutes > 0) return `${minutes}m ${remainder}s`;
      return `${seconds}s`;
    }

    function tickClock() {
      try {
        if (progressClock) progressClock.textContent = new Date().toLocaleTimeString();
        if (progressElapsed) {
          progressElapsed.textContent = formatElapsed(Date.now() - startedAt);
        }
      } catch (_err) {}
    }

    function addLog(line) {
      if (!progressList) return;
      const stripLeadingTime = (value) => {
        try {
          return value.replace(
            /^\s*\d{1,2}:\d{2}(?::\d{2})?\s*(AM|PM)?\s*/i,
            ""
          );
        } catch (_err) {
          return value;
        }
      };
      const li = document.createElement("li");
      const ts = document.createElement("time");
      ts.dateTime = new Date().toISOString();
      ts.textContent = new Date().toLocaleTimeString();
      li.appendChild(ts);
      li.appendChild(document.createTextNode(` ${stripLeadingTime(line)}`));
      progressList.appendChild(li);
      try {
        progressList.scrollTop = progressList.scrollHeight;
      } catch (_err) {}
    }

    function setStep(text, pct) {
      if (progress) progress.style.display = "block";
      if (progressText) progressText.textContent = text;
      if (progressBar && typeof pct === "number") {
        progressBar.style.width = `${pct}%`;
        progressBar.setAttribute("aria-valuenow", pct);
      }
      addLog(text);
    }

    if (loadingIndicator) loadingIndicator.style.display = "block";
    if (btnEl) {
      btnEl.disabled = true;
      const spinner = btnEl.querySelector(".btn-spinner");
      if (spinner) spinner.style.display = "inline-block";
    }

    try {
      if (clockTimer) clearInterval(clockTimer);
    } catch (_err) {}
    try {
      if (progressList) progressList.innerHTML = "";
      if (progressElapsed) progressElapsed.textContent = "0s";
      if (progressClock) progressClock.textContent = new Date().toLocaleTimeString();
      if (progressBar) {
        progressBar.style.width = "10%";
        progressBar.setAttribute("aria-valuenow", 10);
      }
    } catch (_err) {}

    tickClock();
    clockTimer = setInterval(tickClock, 1000);
    setStep("Preparing…", 10);

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
      setStep("Waiting (device)…", 60);
      const result = await handleJsonResponse(response);
      if (response.ok && result && result.success) {
        const metrics = result.metrics || {};
        if (Array.isArray(metrics.steps) && metrics.steps.length) {
          let pct = 60;
          const increment = 30 / metrics.steps.length;
          for (const [name, ms] of metrics.steps) {
            pct += increment;
            setStep(`${name} ${ms} ms`, pct);
            await new Promise((resolve) => setTimeout(resolve, 50));
          }
        }
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
        if (parts.length) {
          const text = parts.join(" • ");
          if (progressText) progressText.textContent = text;
          addLog(text);
        }
        setStep("Display updating…", 90);
        sessionStorage.setItem(
          "storedMessage",
          JSON.stringify({ type: "success", text: `Success! ${result.message}` })
        );
        location.reload();
      }
    } catch (error) {
      console.error("Error:", error);
      showResponseModal(
        "failure",
        "An error occurred while processing your request."
      );
    } finally {
      if (loadingIndicator) loadingIndicator.style.display = "none";
      if (btnEl) {
        btnEl.disabled = false;
        const spinner = btnEl.querySelector(".btn-spinner");
        if (spinner) spinner.style.display = "none";
      }
      setStep("Done", 100);
      try {
        if (clockTimer) clearInterval(clockTimer);
      } catch (_err) {}
      try {
        const lines = Array.from(
          progressList ? progressList.querySelectorAll("li") : [],
          (li) => li.textContent || ""
        );
        const data = {
          finishedAtIso: new Date().toISOString(),
          summary: progressText ? progressText.textContent : "Done",
          lines,
          ctx: {
            page: "playlist",
            playlist: playlistName,
            pluginId,
            instance: pluginInstance,
          },
        };
        const key = ns.buildProgressKey(data.ctx);
        localStorage.setItem(key, JSON.stringify(data));
        localStorage.setItem("INKYPI_LAST_PROGRESS", JSON.stringify(data));
      } catch (_err) {}
      setTimeout(() => {
        if (progress) progress.style.display = "none";
      }, ns.constants.PROGRESS_HIDE_DELAY_MS);
    }
  }

  Object.assign(ns, {
    bindStoredMessageHandler,
    displayPluginInstance,
    restoreStoredMessage,
    showLastProgressGlobal,
  });
})(globalThis);

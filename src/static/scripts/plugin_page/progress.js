/* Progress snapshot and "Last progress" card behavior for plugin pages. */
(function () {
  "use strict";

  function createProgressController({ config, buildProgressKey, setHidden }) {
    function getLastProgressSnapshot() {
      const keys = [
        buildProgressKey(config.progressContext, config),
        `INKYPI_LAST_PROGRESS:plugin:${config.pluginId}:_`,
      ];
      for (const key of keys) {
        const raw = localStorage.getItem(key);
        if (!raw) continue;
        try {
          return JSON.parse(raw);
        } catch (e) {
          console.warn("Corrupt progress data, removing key:", key, e);
          localStorage.removeItem(key);
        }
      }
      return null;
    }

    function syncLastProgressButton() {
      const button = document.getElementById("showLastProgressBtn");
      if (!button) return;
      try {
        const hasSnapshot = !!getLastProgressSnapshot();
        button.disabled = false;
        button.setAttribute("aria-disabled", "false");
        button.title = hasSnapshot
          ? "Show the most recent saved progress log"
          : "Show progress empty state";
      } catch {
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
      }
    }

    function saveLastProgressSnapshot(context) {
      try {
        const list = document.getElementById("requestProgressList");
        const textEl = document.getElementById("requestProgressText");
        const lines = Array.from(list ? list.querySelectorAll("li") : []).map(
          (li) => {
            const timeEl = li.querySelector("time");
            const text = li.textContent || "";
            const timeText = timeEl ? timeEl.textContent || "" : "";
            return timeText && text.startsWith(timeText)
              ? text.slice(timeText.length).trimStart()
              : text.trim();
          }
        );
        const data = {
          finishedAtIso: new Date().toISOString(),
          summary: textEl ? textEl.textContent : "Done",
          lines,
          ctx: context || config.progressContext,
        };
        localStorage.setItem(buildProgressKey(data.ctx, config), JSON.stringify(data));
        localStorage.setItem("INKYPI_LAST_PROGRESS", JSON.stringify(data));
        syncLastProgressButton();
      } catch (e) {
        console.warn("Failed to save progress snapshot:", e);
      }
    }

    function showLastProgress() {
      try {
        const data = getLastProgressSnapshot();
        const finishedAt = new Date(data?.finishedAtIso || "");
        const hasSnapshotData =
          data && Array.isArray(data.lines) && !Number.isNaN(finishedAt.getTime());
        const progress = document.getElementById("requestProgress");
        const textEl = document.getElementById("requestProgressText");
        const clockEl = document.getElementById("requestProgressClock");
        const elapsedEl = document.getElementById("requestProgressElapsed");
        const list = document.getElementById("requestProgressList");
        const bar = document.getElementById("requestProgressBar");
        if (!hasSnapshotData) {
          if (list) {
            list.innerHTML = "";
            const li = document.createElement("li");
            li.className = "progress-empty-state";
            li.textContent =
              "No progress data yet — run Update Now to see progress here.";
            list.appendChild(li);
          }
          if (textEl) textEl.textContent = "No progress data yet";
          if (clockEl) clockEl.textContent = "—";
          if (elapsedEl) elapsedEl.textContent = "—";
          if (bar) {
            bar.style.width = "0%";
            const meter = document.getElementById("requestProgressBarMeter");
            if (meter) meter.value = 0;
          }
          if (progress) {
            setHidden(progress, false);
            progress.style.display = "";
          }
          return;
        }
        if (list) {
          list.innerHTML = "";
          data.lines.forEach((rawLine) => {
            const line = String(rawLine ?? "").replace(
              /^\s*\d{1,2}:\d{2}(?::\d{2})?\s*(AM|PM)?\s*/i,
              ""
            );
            const li = document.createElement("li");
            const ts = document.createElement("time");
            ts.textContent = finishedAt.toLocaleTimeString();
            li.appendChild(ts);
            li.appendChild(document.createTextNode(` ${line}`));
            list.appendChild(li);
          });
        }
        if (textEl) textEl.textContent = data.summary || "Last run";
        if (clockEl) {
          clockEl.textContent = finishedAt.toLocaleTimeString();
        }
        if (elapsedEl) elapsedEl.textContent = "—";
        if (bar) {
          bar.style.width = "100%";
          const meter = document.getElementById("requestProgressBarMeter");
          if (meter) meter.value = 100;
        }
        if (progress) {
          setHidden(progress, false);
          progress.style.display = "";
        }
      } catch (e) {
        console.warn("Failed to show last progress:", e);
      }
    }

    return {
      getLastProgressSnapshot,
      saveLastProgressSnapshot,
      showLastProgress,
      syncLastProgressButton,
    };
  }

  globalThis.InkyPiPluginPageProgress = { createProgressController };
})();

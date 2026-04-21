(function () {
  // Configurable timing defaults (ms). Override via config object.
  const DEFAULTS = {
    pollIntervalMs: 5000,
    refreshDelayMs: 300,
  };

  // Module-scope helpers — hoisted from createDashboardPage (JTN-281).
  function setHidden(node, hidden) {
    if (!node) return;
    node.hidden = hidden;
  }

  function hidePreviewSkeletonNode(previewSkel) {
    if (!previewSkel) return;
    previewSkel.classList.add("is-hidden");
    previewSkel.addEventListener(
      "transitionend",
      () => {
        previewSkel.style.display = "none";
      },
      { once: true }
    );
  }

  function createDashboardPage(config) {
    const pollIntervalMs = config.pollIntervalMs || DEFAULTS.pollIntervalMs;
    const refreshDelayMs = config.refreshDelayMs || DEFAULTS.refreshDelayMs;

    // Store for polling / image-hash state (JTN-502)
    const store = globalThis.InkyPiStore
      ? globalThis.InkyPiStore.createStore({
          imageHash: config.imageHash,
          consecutiveFailures: 0,
        })
      : null;

    // Compatibility shim: read/write via store when available, plain vars otherwise.
    function getImageHash() { return store ? store.get('imageHash') : _legacyImageHash; }
    function setImageHash(v) { if (store) { store.set({ imageHash: v }); } else { _legacyImageHash = v; } }
    function getConsecutiveFailures() { return store ? store.get('consecutiveFailures') : _legacyFailures; }
    function setConsecutiveFailures(v) { if (store) { store.set({ consecutiveFailures: v }); } else { _legacyFailures = v; } }

    // Fallback vars used only when store is not loaded.
    let _legacyImageHash = config.imageHash;
    let _legacyFailures = 0;
    let refreshCountdownTimerId = null;
    let currentRefreshInfo = config.initialRefreshInfo || null;

    const desktopPreviewQuery =
      globalThis.matchMedia &&
      globalThis.matchMedia("(hover: hover) and (pointer: fine)");

    function canUseNativePreview() {
      return !!(desktopPreviewQuery?.matches);
    }

    function syncPreviewMode(container, previewImg) {
      if (!container || !previewImg) return;
      const allowNative = canUseNativePreview();
      container.classList.toggle("native-preview-enabled", allowNative);
      if (!allowNative && container.classList.contains("native")) {
        container.classList.remove("native");
        previewImg.style.width = "";
        previewImg.style.height = "";
      }

      const copy = document.getElementById("dashboardStageCopy");
      if (copy) {
        copy.textContent = allowNative
          ? "Click the preview to inspect it in the lightbox."
          : "Tap the preview to inspect it in the lightbox.";
      }
    }

    function renderMeta(info) {
      const metaDiv = document.getElementById("imageMeta");
      const metaContent = document.getElementById("imageMetaContent");
      if (!metaDiv || !metaContent) return;
      metaContent.innerHTML = "";
      if (!info?.plugin_meta) {
        setHidden(metaDiv, true);
        return;
      }
      const meta = info.plugin_meta;
      const labels = {
        wpotd: "Wikipedia Picture of the Day",
        apod: "NASA APOD",
        newspaper: "Newspaper",
      };
      const rows = [];
      let titleIndex = -1;
      const date = meta.date ? new Date(meta.date).toISOString().slice(0, 10) : "";
      if (date || labels[info.plugin_id]) rows.push(`${labels[info.plugin_id] || info.plugin_id} ${date}`.trim());
      if (meta.title) { titleIndex = rows.length; rows.push(meta.title); }
      if (meta.caption) rows.push(meta.caption);
      if (meta.explanation) rows.push(meta.explanation);
      rows.forEach((text, index) => {
        const row = document.createElement("div");
        row.className = "workflow-meta-row";
        if (index === titleIndex) {
          const em = document.createElement("em");
          em.textContent = text;
          row.appendChild(em);
        } else {
          row.textContent = text;
        }
        metaContent.appendChild(row);
      });
      const link = meta.page_url || meta.description_url || "";
      if (link) {
        const row = document.createElement("div");
        row.className = "workflow-meta-row";
        const anchor = document.createElement("a");
        anchor.href = link;
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        anchor.textContent = "Learn more";
        row.appendChild(anchor);
        metaContent.appendChild(row);
      }
      setHidden(metaDiv, false);
    }

    // setStatusBlock was removed along with #statusRow — the hero-strip below
    // the preview surfaces the same Now/Next information with matching
    // aria-live semantics, so the duplicate aside block was redundant.

    async function refreshPreview() {
      const previewImg = document.getElementById("previewImage");
      const previewSkel = document.getElementById("previewSkeleton");
      let info = null;
      let up = null;
      try {
        [info, up] = await Promise.all([
          fetch(config.refreshInfoUrl).then((response) => response.json()).catch((err) => {
            console.warn("Failed to fetch refresh info:", err);
            return null;
          }),
          fetch(config.nextUpUrl).then((response) => response.json()).catch((err) => {
            console.warn("Failed to fetch next-up info:", err);
            return null;
          }),
        ]);
      } catch (error) {
        console.warn("Dashboard preview refresh failed:", error);
      }

      // Show connectivity warning after repeated failures
      const connWarn = document.getElementById("connectivityWarning");
      if (!info && !up) {
        setConsecutiveFailures(getConsecutiveFailures() + 1);
        if (getConsecutiveFailures() >= 3 && connWarn) {
          setHidden(connWarn, false);
        }
      } else {
        setConsecutiveFailures(0);
        if (connWarn) setHidden(connWarn, true);
      }

      if (info?.image_hash && info.image_hash !== getImageHash() && previewImg) {
        setImageHash(info.image_hash);
        if (previewSkel) { previewSkel.style.display = ''; previewSkel.classList.remove('is-hidden'); }
        setHidden(previewSkel, false);
        previewImg.src = `${config.previewUrl}?t=${Date.now()}`;
      }

      renderMeta(info);
      const overviewEmpty = document.getElementById("overviewEmpty");
      const hasData = info?.plugin_id || up?.plugin_id;
      setHidden(overviewEmpty, hasData);
      updateHeroStrip(info, up);
      if (info?.playlist) {
        setQuickSwitchActiveRow(info.playlist);
      }
    }

    function setCell(valueId, metaId, value, meta, title) {
      const v = document.getElementById(valueId);
      const m = document.getElementById(metaId);
      if (v) {
        v.textContent = value || "\u2014";
        v.classList.toggle("is-empty", !value);
      }
      if (m) {
        m.textContent = meta || "\u2014";
        if (title !== undefined) m.title = title || "";
      }
    }

    function formatRelativeSeconds(iso) {
      if (!iso) return "";
      const ts = Date.parse(iso);
      if (Number.isNaN(ts)) return "";
      const diff = Math.max(0, Math.floor((Date.now() - ts) / 1000));
      if (diff < 60) return `${diff}s ago`;
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    }

    function buildNowMeta(info) {
      // Handoff parity: "Playlist: Morning · refreshed 3 min ago". When no
      // playlist is attached fall back to the refresh_type so the meta row
      // never collapses unless there is genuinely no info.
      if (!info) return "";
      const rel = formatRelativeSeconds(info.refresh_time);
      if (info.playlist) {
        return rel
          ? `Playlist: ${info.playlist} \u00B7 refreshed ${rel}`
          : `Playlist: ${info.playlist}`;
      }
      if (info.refresh_type) return info.refresh_type;
      return "";
    }

    function parseIsoDate(iso) {
      if (!iso) return null;
      const parsed = new Date(iso);
      return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function formatClockTime(date) {
      if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
      return new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit",
      }).format(date);
    }

    function resolveCycleMinutes(info) {
      const raw = info?.cycle_minutes ?? config.cycleMinutes;
      const mins = Number(raw);
      return Number.isFinite(mins) && mins > 0 ? mins : null;
    }

    function resolveNextRefreshTime(info) {
      const annotated = parseIsoDate(info?.next_refresh_time);
      if (annotated) return annotated;

      const refreshAt = parseIsoDate(info?.refresh_time);
      const cycleMinutes = resolveCycleMinutes(info);
      if (!refreshAt || !cycleMinutes) return null;
      return new Date(refreshAt.getTime() + cycleMinutes * 60 * 1000);
    }

    function formatCountdownLabel(nextRefreshAt) {
      if (!(nextRefreshAt instanceof Date) || Number.isNaN(nextRefreshAt.getTime())) {
        return "";
      }

      const diffMs = nextRefreshAt.getTime() - Date.now();
      if (diffMs <= 30 * 1000) return "Due now";

      const diffSeconds = Math.ceil(diffMs / 1000);
      if (diffSeconds < 60) return `in ${diffSeconds}s`;

      const diffMinutes = Math.ceil(diffSeconds / 60);
      if (diffMinutes < 60) return `in ${diffMinutes}m`;

      const hours = Math.floor(diffMinutes / 60);
      const minutes = diffMinutes % 60;
      if (hours < 24) {
        return minutes ? `in ${hours}h ${minutes}m` : `in ${hours}h`;
      }

      return `at ${formatClockTime(nextRefreshAt)}`;
    }

    function buildRefreshMeta(nextRefreshAt, cycleMinutes, info) {
      // Handoff replaces raw request latency with the cycle cadence so users
      // see when the next refresh is coming, not how long the last one took.
      if (info?.next_refresh_meta) {
        return info.next_refresh_meta;
      }
      const parts = [];
      if (nextRefreshAt) {
        parts.push(`ETA ${formatClockTime(nextRefreshAt)}`);
      }
      if (cycleMinutes) {
        parts.push(`Every ${cycleMinutes} min`);
      }
      parts.push("auto");
      return parts.join(" \u00B7 ");
    }

    function renderRefreshCountdown() {
      const nextRefreshAt = resolveNextRefreshTime(currentRefreshInfo);
      const cycleMinutes = resolveCycleMinutes(currentRefreshInfo);
      setCell(
        "heroRefreshValue",
        "heroRefreshMeta",
        formatCountdownLabel(nextRefreshAt),
        buildRefreshMeta(nextRefreshAt, cycleMinutes, currentRefreshInfo),
        currentRefreshInfo?.next_refresh_time || (nextRefreshAt ? nextRefreshAt.toISOString() : ""),
      );
    }

    function updateRefreshCountdown(info) {
      currentRefreshInfo = info || null;
      renderRefreshCountdown();
    }

    function startRefreshCountdown() {
      renderRefreshCountdown();
      if (refreshCountdownTimerId) {
        clearInterval(refreshCountdownTimerId);
      }
      refreshCountdownTimerId = globalThis.setInterval(renderRefreshCountdown, 1000);
    }

    function updateHeroStrip(info, up) {
      const nowValue = info?.plugin_id ? (info.plugin_display_name || info.plugin_id) : "";
      setCell("heroNowValue", "heroNowMeta", nowValue || "Idle", buildNowMeta(info));
      const nowV = document.getElementById("heroNowValue");
      if (nowV) nowV.classList.toggle("is-empty", !nowValue);

      const nextValue = up?.plugin_id ? (up.plugin_display_name || up.plugin_id) : "";
      const nextMeta = up?.playlist ? `Playlist: ${up.playlist}` : "";
      setCell("heroNextValue", "heroNextMeta", nextValue, nextMeta);
      updateRefreshCountdown(info);
    }

    function setQuickSwitchButtonPending(button, pending) {
      if (!button) return;
      const defaultLabel = button.dataset.defaultLabel || button.textContent || "Switch now";
      button.dataset.defaultLabel = defaultLabel;
      button.disabled = !!pending;
      button.classList.toggle("is-busy", !!pending);
      button.textContent = pending ? "Switching…" : defaultLabel;
    }

    function setQuickSwitchActiveRow(playlistName) {
      if (!playlistName) return;
      document.querySelectorAll("[data-quick-switch-row]").forEach((row) => {
        const isActive = row.dataset.playlistName === playlistName;
        row.classList.toggle("is-active", isActive);

        const status = row.querySelector("[data-quick-switch-status]");
        if (status) setHidden(status, !isActive);

        const button = row.querySelector("[data-quick-switch-button]");
        if (button) {
          setHidden(button, isActive);
          button.disabled = isActive;
          button.setAttribute("aria-hidden", isActive ? "true" : "false");
          if (!isActive) {
            setQuickSwitchButtonPending(button, false);
          }
        }

        const fallback = row.querySelector("[data-quick-switch-fallback]");
        if (fallback) {
          setHidden(fallback, isActive);
          fallback.setAttribute("aria-hidden", isActive ? "true" : "false");
        }
      });
    }

    async function quickSwitchPlaylist(playlistName, button) {
      if (!playlistName || !config.quickSwitchUrl) return;
      setQuickSwitchButtonPending(button, true);
      try {
        const response = await fetch(config.quickSwitchUrl, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ playlist_name: playlistName }),
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
          showResponseModal(
            "failure",
            `Failed to switch playlist: ${result.error || "Unknown error"}`
          );
          return;
        }
        setQuickSwitchActiveRow(result.playlist || playlistName);
        setTimeout(() => {
          refreshPreview();
          refreshKpis();
        }, refreshDelayMs);
      } catch (error) {
        showResponseModal("failure", "Failed to switch playlist");
      } finally {
        setQuickSwitchButtonPending(button, false);
      }
    }

    async function displayNextNow() {
      const button = document.getElementById("displayNextBtn");
      const buttonLabel = button?.querySelector(".button-text");
      if (button) {
          button.disabled = true;
          if (buttonLabel) {
            buttonLabel.textContent = "Displaying\u2026";
          } else {
            button.textContent = "Displaying\u2026";
          }
          button.classList.add("loading");
      }
      try {
        const response = await fetch(config.displayNextUrl, { method: "POST" });
        const result = await response.json();
        if (!response.ok || !result.success) {
          showResponseModal("failure", `Failed to display next: ${result.error || "Unknown error"}`);
        } else {
          setTimeout(refreshPreview, refreshDelayMs);
        }
      } catch (error) {
        showResponseModal("failure", "Failed to display next");
      } finally {
        if (button) {
            button.disabled = false;
            if (buttonLabel) {
              buttonLabel.textContent = button.dataset.defaultLabel || "Display Next";
            } else {
              button.textContent = button.dataset.defaultLabel || "Display Next";
            }
            button.classList.remove("loading");
        }
      }
    }

    function initPreviewInteractions() {
      const previewImg = document.getElementById("previewImage");
      const previewSkel = document.getElementById("previewSkeleton");
      const container = previewImg?.parentElement;
      const hidePreviewSkeleton = () => hidePreviewSkeletonNode(previewSkel);
      if (previewImg) {
        previewImg.addEventListener("load", hidePreviewSkeleton);
        previewImg.addEventListener("error", hidePreviewSkeleton);
        if (previewImg.complete && previewImg.naturalWidth > 0) {
          hidePreviewSkeleton();
        }
        previewImg.addEventListener("click", () => {
          if (previewImg.src && globalThis.Lightbox) globalThis.Lightbox.open(previewImg.src, previewImg.alt);
        });
        previewImg.style.cursor = "pointer";
        previewImg.setAttribute("role", "button");
        previewImg.setAttribute("tabindex", "0");
        previewImg.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (previewImg.src && globalThis.Lightbox) globalThis.Lightbox.open(previewImg.src, previewImg.alt);
          }
        });
      }
      if (previewImg && container) {
        const nativeWidth = previewImg.dataset.nativeWidth || config.resolution[0];
        const nativeHeight = previewImg.dataset.nativeHeight || config.resolution[1];
        const fitBtn = document.getElementById("previewFitBtn");
        const nativeBtn = document.getElementById("previewNativeBtn");

        function applyPreviewMode(native) {
          const want = !!native && canUseNativePreview();
          container.classList.toggle("native", want);
          if (want) {
            previewImg.style.width = `${nativeWidth}px`;
            previewImg.style.height = `${nativeHeight}px`;
          } else {
            previewImg.style.width = "";
            previewImg.style.height = "";
          }
          if (fitBtn && nativeBtn) {
            fitBtn.classList.toggle("active", !want);
            fitBtn.setAttribute("aria-pressed", String(!want));
            nativeBtn.classList.toggle("active", want);
            nativeBtn.setAttribute("aria-pressed", String(want));
            nativeBtn.disabled = !canUseNativePreview();
          }
        }

        syncPreviewMode(container, previewImg);
        applyPreviewMode(false);
        previewImg.addEventListener("dblclick", (event) => {
          if (!canUseNativePreview()) return;
          event.preventDefault();
          applyPreviewMode(!container.classList.contains("native"));
        });
        if (fitBtn) fitBtn.addEventListener("click", () => applyPreviewMode(false));
        if (nativeBtn) nativeBtn.addEventListener("click", () => applyPreviewMode(true));
        if (desktopPreviewQuery && typeof desktopPreviewQuery.addEventListener === "function") {
          desktopPreviewQuery.addEventListener("change", () => { syncPreviewMode(container, previewImg); applyPreviewMode(container.classList.contains("native")); });
        }
        globalThis.addEventListener("resize", () => syncPreviewMode(container, previewImg));
      }
    }

    function startPolling() {
      refreshPreview();
      return setInterval(refreshPreview, pollIntervalMs);
    }

    function initRealtime() {
      let pollTimerId = null;
      let sseSource = null;

      function cleanup() {
        if (sseSource) { sseSource.close(); sseSource = null; }
        if (pollTimerId) { clearInterval(pollTimerId); pollTimerId = null; }
      }

      globalThis.addEventListener("beforeunload", cleanup);
      globalThis.addEventListener("pagehide", cleanup);

      const pushUrl = config.pushUrl;
      if (pushUrl && globalThis.EventSource) {
        try {
          sseSource = new EventSource(pushUrl);
          sseSource.onmessage = () => refreshPreview();
          sseSource.onerror = () => {
            console.warn("SSE connection lost, falling back to polling");
            if (sseSource) { sseSource.close(); sseSource = null; }
            refreshPreview();
            pollTimerId = setInterval(refreshPreview, pollIntervalMs);
          };
          return;
        } catch (error) {
          console.warn("SSE not available, using polling:", error);
        }
      }
      refreshPreview();
      pollTimerId = setInterval(refreshPreview, pollIntervalMs);
    }

    function init() {
      // Hide plugin icons that fail to load
      document.querySelectorAll('.plugin-item img.icon-image[loading="lazy"]').forEach(function (img) {
        img.addEventListener('error', function () {
          img.style.display = 'none';
          const fallback = document.createElement('span');
          fallback.className = 'icon-image icon-fallback';
          fallback.setAttribute('aria-hidden', 'true');
          fallback.textContent = '?';
          img.parentNode.insertBefore(fallback, img.nextSibling);
        });
      });
      // JTN-214: Defensive check — log broken plugin card links
      document.querySelectorAll('.plugins-container .plugin-item').forEach(function(el) {
        if (!el.getAttribute('href')) {
          console.warn('Plugin card missing href:', el.textContent.trim());
        }
      });
      document.querySelectorAll("[data-quick-switch-button]").forEach((button) => {
        button.addEventListener("click", () => {
          quickSwitchPlaylist(button.dataset.playlistName, button);
        });
      });
      document.getElementById("displayNextBtn")?.addEventListener("click", displayNextNow);
      document.getElementById("dashboardRefreshBtn")?.addEventListener("click", () => {
        // Manually re-fetch preview + refresh info + next-up; mirrors the
        // realtime SSE handler but triggered by user gesture.
        refreshPreview();
        refreshKpis();
      });
      globalThis.addEventListener("beforeunload", () => {
        if (refreshCountdownTimerId) {
          clearInterval(refreshCountdownTimerId);
          refreshCountdownTimerId = null;
        }
      });
      globalThis.addEventListener("pagehide", () => {
        if (refreshCountdownTimerId) {
          clearInterval(refreshCountdownTimerId);
          refreshCountdownTimerId = null;
        }
      });
      startRefreshCountdown();
      initPreviewInteractions();
      initRealtime();
      refreshKpis();
    }

    // Today KPI card — populated from /api/stats (24h window) + /api/health/system.
    async function refreshKpis() {
      const setText = (id, value, extraClass) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = value;
        if (extraClass !== undefined) {
          el.className = extraClass ? `${extraClass}` : "";
        }
      };
      const setStatus = (value) => {
        const el = document.getElementById("todayKpiSub");
        if (!el) return;
        el.textContent = value;
      };

      const statsUrl = config.statsUrl || "/api/stats";
      const healthUrl = config.systemHealthUrl || "/api/health/system";
      let statsReachable = false;
      let healthReachable = false;
      let hasTelemetry = false;

      try {
        const resp = await fetch(statsUrl, { headers: { Accept: "application/json" } });
        if (resp.ok) {
          statsReachable = true;
          const body = await resp.json();
          const w = body.last_24h || {};
          const total = Number(w.total);
          setText("kpiRefreshes", Number.isFinite(total) ? String(total) : "—");
          const p50 = Number(w.p50_duration_ms);
          setText("kpiAvgRender", Number.isFinite(p50) && p50 > 0 ? `${(p50 / 1000).toFixed(1)} s` : "—");
          const errs = Number.isFinite(w.failure) ? Number(w.failure) : NaN;
          setText("kpiErrors", Number.isFinite(errs) ? String(errs) : "—", errs === 0 ? "ok" : errs > 0 ? "warn" : "");
          hasTelemetry = hasTelemetry || Number.isFinite(total) || (Number.isFinite(p50) && p50 > 0) || Number.isFinite(errs);
        }
      } catch (error) {
        console.warn("Failed to fetch refresh stats:", error);
      }

      try {
        const resp = await fetch(healthUrl, { headers: { Accept: "application/json" } });
        if (resp.ok) {
          healthReachable = true;
          const body = await resp.json();
          const free = Number(body.disk_free_gb);
          setText("kpiStorageFree", Number.isFinite(free) ? `${free.toFixed(1)} GB` : "—");
          hasTelemetry = hasTelemetry || Number.isFinite(free);
        }
      } catch (error) {
        console.warn("Failed to fetch system health:", error);
      }

      if (hasTelemetry) {
        setStatus("Last 24h snapshot");
      } else if (statsReachable || healthReachable) {
        setStatus("Awaiting telemetry");
      } else {
        setStatus("Telemetry unavailable");
      }
    }

    return { init };
  }

  globalThis.InkyPiDashboardPage = { create: createDashboardPage };
})();

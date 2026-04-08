(function () {
  // Configurable timing defaults (ms). Override via config object.
  const DEFAULTS = {
    pollIntervalMs: 5000,
    refreshDelayMs: 300,
  };

  function createDashboardPage(config) {
    const pollIntervalMs = config.pollIntervalMs || DEFAULTS.pollIntervalMs;
    const refreshDelayMs = config.refreshDelayMs || DEFAULTS.refreshDelayMs;
    let lastImageHash = config.imageHash;
    const desktopPreviewQuery =
      globalThis.matchMedia &&
      globalThis.matchMedia("(hover: hover) and (pointer: fine)");

    function setHidden(node, hidden) {
      if (!node) return;
      node.hidden = hidden;
    }

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
          ? "Click the preview to inspect it in the lightbox. On desktop, double-click to toggle native pixels."
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

    function setStatusBlock(prefix, data) {
      const block = document.getElementById(`${prefix}Block`);
      const plugin = document.getElementById(`${prefix === "nowShowing" ? "ns" : "nu"}Plugin`);
      const instance = document.getElementById(`${prefix === "nowShowing" ? "ns" : "nu"}Instance`);
      const playlist = document.getElementById(`${prefix === "nowShowing" ? "ns" : "nu"}Playlist`);
      if (!block || !plugin || !instance || !playlist) return;
      if (!data || !data.plugin_id) {
        setHidden(block, true);
        return;
      }
      setHidden(block, false);
      plugin.textContent = data.plugin_id || "";
      instance.textContent = data.plugin_instance || "";
      playlist.textContent = data.playlist || "";
      setHidden(instance, !data.plugin_instance);
      setHidden(playlist, !data.playlist);
    }

    let consecutiveFailures = 0;

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
        consecutiveFailures++;
        if (consecutiveFailures >= 3 && connWarn) {
          setHidden(connWarn, false);
        }
      } else {
        consecutiveFailures = 0;
        if (connWarn) setHidden(connWarn, true);
      }

      if (info?.image_hash && info.image_hash !== lastImageHash && previewImg) {
        lastImageHash = info.image_hash;
        if (previewSkel) { previewSkel.style.display = ''; previewSkel.classList.remove('is-hidden'); }
        setHidden(previewSkel, false);
        previewImg.src = `${config.previewUrl}?t=${Date.now()}`;
      }

      renderMeta(info);
      setStatusBlock("nowShowing", info);
      setStatusBlock("nextUp", up);
      const row = document.getElementById("statusRow");
      setHidden(row, !info?.plugin_id && !up?.plugin_id);
      const overviewEmpty = document.getElementById("overviewEmpty");
      const hasData = info?.plugin_id || up?.plugin_id;
      setHidden(overviewEmpty, hasData);
    }

    async function displayNextNow() {
      const button = document.getElementById("displayNextBtn");
      if (button) {
          button.disabled = true;
          button.textContent = "Displaying\u2026";
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
            button.textContent = "Display Next";
            button.classList.remove("loading");
        }
      }
    }

    function initPreviewInteractions() {
      const previewImg = document.getElementById("previewImage");
      const previewSkel = document.getElementById("previewSkeleton");
      const container = previewImg?.parentElement;
      const hidePreviewSkeleton = () => {
        if (!previewSkel) return;
        previewSkel.classList.add('is-hidden');
        previewSkel.addEventListener('transitionend', () => { previewSkel.style.display = 'none'; }, { once: true });
      };
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
        syncPreviewMode(container, previewImg);
        previewImg.addEventListener("dblclick", (event) => {
          if (!canUseNativePreview()) return;
          event.preventDefault();
          container.classList.toggle("native");
          if (container.classList.contains("native")) {
            previewImg.style.width = `${nativeWidth}px`;
            previewImg.style.height = `${nativeHeight}px`;
          } else {
            previewImg.style.width = "";
            previewImg.style.height = "";
          }
        });
        if (desktopPreviewQuery && typeof desktopPreviewQuery.addEventListener === "function") {
          desktopPreviewQuery.addEventListener("change", () => syncPreviewMode(container, previewImg));
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
      document.getElementById("displayNextBtn")?.addEventListener("click", displayNextNow);
      initPreviewInteractions();
      initRealtime();
    }

    return { init };
  }

  globalThis.InkyPiDashboardPage = { create: createDashboardPage };
})();

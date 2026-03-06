(function () {
  function createDashboardPage(config) {
    let lastImageHash = config.imageHash;

    function setHidden(node, hidden) {
      if (!node) return;
      node.hidden = hidden;
    }

    function renderMeta(info) {
      const metaDiv = document.getElementById("imageMeta");
      const metaContent = document.getElementById("imageMetaContent");
      if (!metaDiv || !metaContent) return;
      metaContent.innerHTML = "";
      if (!(info && info.plugin_meta)) {
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
      const date = meta.date ? new Date(meta.date).toISOString().slice(0, 10) : "";
      if (date || labels[info.plugin_id]) rows.push(`${labels[info.plugin_id] || info.plugin_id} ${date}`.trim());
      if (meta.title) rows.push(meta.title);
      if (meta.caption) rows.push(meta.caption);
      if (meta.explanation) rows.push(meta.explanation);
      rows.forEach((text, index) => {
        const row = document.createElement("div");
        row.className = "workflow-meta-row";
        if (index === 1 && meta.title) {
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

    async function refreshPreview() {
      const previewImg = document.getElementById("previewImage");
      const previewSkel = document.getElementById("previewSkeleton");
      let info = null;
      let up = null;
      try {
        [info, up] = await Promise.all([
          fetch(config.refreshInfoUrl).then((response) => response.json()).catch(() => null),
          fetch(config.nextUpUrl).then((response) => response.json()).catch(() => null),
        ]);
      } catch (error) {}

      if (info && info.image_hash && info.image_hash !== lastImageHash && previewImg) {
        lastImageHash = info.image_hash;
        setHidden(previewSkel, false);
        previewImg.src = `${config.previewUrl}?t=${Date.now()}`;
      }

      renderMeta(info);
      setStatusBlock("nowShowing", info);
      setStatusBlock("nextUp", up);
      const row = document.getElementById("statusRow");
      setHidden(row, !(info && info.plugin_id) && !(up && up.plugin_id));
    }

    async function displayNextNow() {
      const button = document.getElementById("displayNextBtn");
      if (button) button.disabled = true;
      try {
        const response = await fetch(config.displayNextUrl, { method: "POST" });
        const result = await response.json();
        if (!response.ok || !result.success) {
          showResponseModal("failure", `Failed to display next: ${result.error || "Unknown error"}`);
        } else {
          setTimeout(refreshPreview, 300);
        }
      } catch (error) {
        showResponseModal("failure", "Failed to display next");
      } finally {
        if (button) button.disabled = false;
      }
    }

    function initPreviewInteractions() {
      const previewImg = document.getElementById("previewImage");
      const previewSkel = document.getElementById("previewSkeleton");
      const container = previewImg && previewImg.parentElement;
      if (previewImg) {
        previewImg.addEventListener("load", () => setHidden(previewSkel, true));
        previewImg.addEventListener("error", () => setHidden(previewSkel, true));
        previewImg.addEventListener("click", () => {
          if (previewImg.src && window.Lightbox) window.Lightbox.open(previewImg.src, previewImg.alt);
        });
      }
      if (previewImg && container) {
        const nativeWidth = previewImg.dataset.nativeWidth || config.resolution[0];
        const nativeHeight = previewImg.dataset.nativeHeight || config.resolution[1];
        previewImg.addEventListener("dblclick", (event) => {
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
      }
    }

    function startPolling() {
      refreshPreview();
      return setInterval(refreshPreview, 5000);
    }

    function initRealtime() {
      const pushUrl = config.pushUrl;
      if (pushUrl && window.EventSource) {
        try {
          const source = new EventSource(pushUrl);
          source.onmessage = () => refreshPreview();
          source.onerror = () => {
            source.close();
            startPolling();
          };
          return;
        } catch (error) {}
      }
      startPolling();
    }

    function init() {
      document.getElementById("displayNextBtn")?.addEventListener("click", displayNextNow);
      initPreviewInteractions();
      initRealtime();
    }

    return { init };
  }

  window.InkyPiDashboardPage = { create: createDashboardPage };
})();

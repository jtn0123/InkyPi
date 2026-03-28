(function () {
  function createPluginPage(config) {
    const ui = window.InkyPiUI || {};
    const mobileQuery = window.matchMedia ? window.matchMedia("(max-width: 768px)") : { matches: false, addEventListener() {} };
    const uploadedFiles = (window.uploadedFiles = window.uploadedFiles || {});
    let workflowMode = "configure";

    function syncModalOpenState() {
      if (ui.syncModalOpenState) return ui.syncModalOpenState();
      var open = document.querySelector(".modal.is-open");
      document.body.classList.toggle("modal-open", !!open);
    }

    function setHidden(node, hidden) {
      if (!node) return;
      node.hidden = hidden;
      node.classList.toggle("is-hidden", hidden);
    }

    function buildProgressKey(ctx) {
      if (ctx && ctx.page === "plugin") {
        const pid = ctx.pluginId || config.pluginId;
        const inst = ctx.instance || "";
        return `INKYPI_LAST_PROGRESS:plugin:${pid}:${inst || "_"}`;
      }
      return "INKYPI_LAST_PROGRESS";
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
        localStorage.setItem(buildProgressKey(data.ctx), JSON.stringify(data));
        localStorage.setItem("INKYPI_LAST_PROGRESS", JSON.stringify(data));
      } catch (e) { console.warn("Failed to save progress snapshot:", e); }
    }

    function showLastProgress() {
      try {
        const keys = [
          buildProgressKey(config.progressContext),
          `INKYPI_LAST_PROGRESS:plugin:${config.pluginId}:_`,
          "INKYPI_LAST_PROGRESS",
        ];
        let data = null;
        for (const key of keys) {
          const raw = localStorage.getItem(key);
          if (raw) {
            data = JSON.parse(raw);
            break;
          }
        }
        if (!data) {
          showResponseModal("failure", "No recent progress to show");
          return;
        }
        const progress = document.getElementById("requestProgress");
        const textEl = document.getElementById("requestProgressText");
        const clockEl = document.getElementById("requestProgressClock");
        const elapsedEl = document.getElementById("requestProgressElapsed");
        const list = document.getElementById("requestProgressList");
        const bar = document.getElementById("requestProgressBar");
        if (list) {
          list.innerHTML = "";
          data.lines.forEach((rawLine) => {
            const line = rawLine.replace(
              /^\s*\d{1,2}:\d{2}(?::\d{2})?\s*(AM|PM)?\s*/i,
              ""
            );
            const li = document.createElement("li");
            const ts = document.createElement("time");
            ts.textContent = new Date(data.finishedAtIso).toLocaleTimeString();
            li.appendChild(ts);
            li.appendChild(document.createTextNode(` ${line}`));
            list.appendChild(li);
          });
        }
        if (textEl) textEl.textContent = data.summary || "Last run";
        if (clockEl) {
          clockEl.textContent = new Date(data.finishedAtIso).toLocaleTimeString();
        }
        if (elapsedEl) elapsedEl.textContent = "—";
        if (bar) { bar.style.width = "100%"; bar.setAttribute("aria-valuenow", 100); }
        if (progress) progress.style.display = "block";
      } catch (e) { console.warn("Failed to show last progress:", e); }
    }

    function renderMetaBlock(metaDiv, metaContent, info) {
      if (!metaDiv || !metaContent) return;
      metaContent.innerHTML = "";
      if (!(info && info.plugin_meta)) {
        setHidden(metaDiv, true);
        return;
      }
      const m = info.plugin_meta || {};
      const pid = info.plugin_id || "";
      const date = m.date ? new Date(m.date).toISOString().slice(0, 10) : "";
      const labels = {
        wpotd: "Wikipedia Picture of the Day",
        apod: "NASA APOD",
        newspaper: "Newspaper",
      };
      const rows = [];
      if (date || labels[pid]) {
        rows.push({
          strong: labels[pid] || pid,
          text: date,
        });
      }
      if (m.title) rows.push({ italic: m.title });
      if (m.caption) rows.push({ text: m.caption });
      if (m.explanation) rows.push({ text: m.explanation });
      rows.forEach((row) => {
        const block = document.createElement("div");
        block.className = "workflow-meta-row";
        if (row.strong) {
          const strong = document.createElement("strong");
          strong.textContent = row.strong;
          block.appendChild(strong);
          if (row.text) block.appendChild(document.createTextNode(` ${row.text}`));
        } else if (row.italic) {
          const em = document.createElement("em");
          em.textContent = row.italic;
          block.appendChild(em);
        } else if (row.text) {
          block.textContent = row.text;
        }
        metaContent.appendChild(block);
      });
      const link = m.page_url || m.description_url || "";
      if (link) {
        const linkRow = document.createElement("div");
        linkRow.className = "workflow-meta-row";
        const anchor = document.createElement("a");
        anchor.href = link;
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        anchor.textContent = "Learn more";
        linkRow.appendChild(anchor);
        metaContent.appendChild(linkRow);
      }
      setHidden(metaDiv, metaContent.childNodes.length === 0);
    }

    async function handleAction(action, triggerButton) {
      try {
        if (typeof window.validatePluginSettings === "function") {
          const isValid = window.validatePluginSettings(action);
          if (!isValid) return;
        }
      } catch (e) {
        console.warn("Plugin validation threw an error:", e);
      }

      if (!window.PluginForm || typeof window.PluginForm.sendForm !== "function") {
        showResponseModal(
          "failure",
          "Plugin form module failed to load. Refresh and try again."
        );
        return;
      }

      if (triggerButton) triggerButton.disabled = true;
      try {
        await window.PluginForm.sendForm({
          action,
          urls: config.urls,
          uploadedFiles,
          onAfterSuccess: () => {
            setTimeout(() => {
              refreshPreviewImage();
              refreshInstancePreview();
            }, 250);
            closeModal("scheduleModal");
          },
        });
        saveLastProgressSnapshot(config.progressContext);
      } finally {
        if (triggerButton) triggerButton.disabled = false;
      }
    }

    async function refreshPreviewImage() {
      const img = document.getElementById("previewImage");
      const skel = document.getElementById("previewSkeleton");
      if (img) {
        if (skel) { skel.style.display = ""; skel.classList.remove("is-hidden"); }
        img.src = `${config.previewUrl}?t=${Date.now()}`;
      }

      try {
        const res = await fetch(config.refreshInfoUrl);
        const info = await res.json();
        const ts = info && info.refresh_time ? new Date(info.refresh_time) : null;
        const currTime = document.getElementById("currentDisplayTime");
        if (currTime) currTime.textContent = ts ? ts.toLocaleString() : "—";
        const metaDiv = document.getElementById("pluginMeta");
        const metaContent = document.getElementById("pluginMetaContent");
        renderMetaBlock(metaDiv, metaContent, info);
      } catch (e) {}
    }

    function openModal(modalId) {
      const modal = document.getElementById(modalId);
      if (!modal) return;
      modal.hidden = false;
      modal.style.display = "flex";
      modal.classList.add("is-open");
      syncModalOpenState();
    }

    function closeModal(modalId) {
      const modal = document.getElementById(modalId);
      if (!modal) return;
      modal.hidden = true;
      modal.style.display = "none";
      modal.classList.remove("is-open");
      syncModalOpenState();
    }

    function selectedFrame(element) {
      const previous = document.querySelector(".image-option.selected");
      if (previous) previous.classList.remove("selected");
      element.classList.add("selected");
      document.getElementById("selected-frame").value =
        element.getAttribute("data-face-name");
    }

    function showFileName() {
      const fileInput = document.getElementById("imageUpload");
      const fileNameDisplay = document.getElementById("fileName");
      const fileNameText = document.getElementById("fileNameText");
      const uploadButtonLabel = document.getElementById("uploadButtonLabel");
      const removeFileButton = document.getElementById("removeFileButton");
      const file = fileInput && fileInput.files && fileInput.files[0];
      if (!fileNameDisplay || !fileNameText || !uploadButtonLabel || !removeFileButton) {
        return;
      }
      if (file) {
        fileNameText.textContent = file.name;
        setHidden(fileNameDisplay, false);
        setHidden(uploadButtonLabel, true);
      } else {
        setHidden(fileNameDisplay, true);
        setHidden(uploadButtonLabel, false);
      }
    }

    function removeFile() {
      const fileInput = document.getElementById("imageUpload");
      const fileNameDisplay = document.getElementById("fileName");
      const uploadButtonLabel = document.getElementById("uploadButtonLabel");
      if (fileInput) fileInput.value = "";
      setHidden(fileNameDisplay, true);
      setHidden(uploadButtonLabel, false);
      const hidden = document.getElementById("hidden-file-name");
      if (hidden) hidden.remove();
    }

    function populateStyleSettings() {
      if (!config.styleSettings || !config.loadPluginSettings) return;
      const settings = config.pluginSettings || {};
      Object.entries(settings).forEach(([key, value]) => {
        const input = document.getElementById(key);
        if (!input || value == null || value === "") return;
        if (input.type === "checkbox") {
          input.checked = !!value;
        } else {
          input.value = value;
        }
      });
    }

    async function resolveAvailableImageUrl(url) {
      if (!url) return null;
      const probeUrl = `${url}${url.includes("?") ? "&" : "?"}probe=${Date.now()}`;
      try {
        const response = await fetch(probeUrl, {
          method: "HEAD",
          cache: "no-store",
        });
        if (response.ok) return url;
      } catch (error) {}
      return null;
    }

    async function refreshInstancePreview() {
      const instImgEl = document.getElementById("instancePreviewImage");
      if (!instImgEl) return;
      const skeleton = instImgEl.previousElementSibling;
      const fallback = document.getElementById("instancePreviewFallback");
      setHidden(skeleton, false);
      setHidden(fallback, true);
      setHidden(instImgEl, false);

      // Avoid probing image endpoints before the backend has ever produced
      // output for this plugin or instance. That state is expected on a fresh
      // page and should render the empty fallback without console noise.
      if (!config.lastRefresh) {
        setHidden(instImgEl, true);
        setHidden(skeleton, true);
        setHidden(fallback, false);
        return;
      }

      const primaryUrl = await resolveAvailableImageUrl(config.instanceImageUrl);
      const fallbackUrl =
        primaryUrl === config.latestPluginImageUrl
          ? primaryUrl
          : await resolveAvailableImageUrl(config.latestPluginImageUrl);
      const imageUrl = primaryUrl || fallbackUrl;
      if (!imageUrl) {
        setHidden(instImgEl, true);
        setHidden(skeleton, true);
        setHidden(fallback, false);
        return;
      }

      instImgEl.src = `${imageUrl}?t=${Date.now()}`;
      instImgEl.onload = function () {
        setHidden(skeleton, true);
      };
      instImgEl.onerror = function () {
        if (primaryUrl && imageUrl === primaryUrl && fallbackUrl && fallbackUrl !== primaryUrl) {
          this.src = `${fallbackUrl}?t=${Date.now()}`;
          this.onerror = function () {
            setHidden(this, true);
            setHidden(skeleton, true);
            setHidden(fallback, false);
          };
          return;
        }
        setHidden(this, true);
        setHidden(skeleton, true);
        setHidden(fallback, false);
      };
    }

    async function displayInstanceNow() {
      try {
        const resp = await fetch(config.displayInstanceUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(config.displayInstancePayload),
        });
        const result = await resp.json();
        if (!resp.ok) {
          showResponseModal("failure", `Error! ${result.error}`);
        } else {
          showResponseModal("success", `Success! ${result.message}`);
          setTimeout(() => {
            refreshPreviewImage();
            refreshInstancePreview();
          }, 400);
        }
      } catch (e) {
        showResponseModal("failure", "Failed to display instance");
      }
    }

    function initStatusBar() {
      const instTimeEl = document.getElementById("instanceLastTime");
      if (instTimeEl) {
        instTimeEl.textContent = config.lastRefresh
          ? new Date(config.lastRefresh).toLocaleString()
          : "—";
      }
      refreshPreviewImage();
      refreshInstancePreview();
    }

    function fadeSkeleton(skel) {
      if (!skel) return;
      skel.classList.add('is-hidden');
      skel.addEventListener('transitionend', () => { skel.style.display = 'none'; }, { once: true });
    }

    function initPreviewInteractions() {
      const previewImg = document.getElementById("previewImage");
      const instanceImg = document.getElementById("instancePreviewImage");
      const container = document.getElementById("currentPreviewContainer");
      if (previewImg && container) {
        const previewSkel = document.getElementById("previewSkeleton");
        previewImg.addEventListener("load", () => fadeSkeleton(previewSkel));
        previewImg.addEventListener("error", () => fadeSkeleton(previewSkel));
        const nativeWidth = previewImg.dataset.nativeWidth || config.resolution[0];
        const nativeHeight = previewImg.dataset.nativeHeight || config.resolution[1];
        previewImg.addEventListener("click", () => {
          if (previewImg.src && window.Lightbox) {
            window.Lightbox.open(previewImg.src, previewImg.alt);
          }
        });
        if (!container.closest(".status-card.compact")) {
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
      if (instanceImg) {
        const skeleton = instanceImg.previousElementSibling;
        instanceImg.addEventListener("load", () => fadeSkeleton(skeleton));
        instanceImg.addEventListener("click", () => {
          if (
            instanceImg.src &&
            !instanceImg.hidden &&
            window.Lightbox
          ) {
            window.Lightbox.open(instanceImg.src, instanceImg.alt);
          }
        });
      }
      document.addEventListener("click", (event) => {
        const img = event.target.closest("img.lightboxable");
        if (!img || !window.Lightbox || !img.src) return;
        event.preventDefault();
        window.Lightbox.open(img.src, img.alt || "Preview");
      });
      const toggle = document.getElementById("toggleDeviceFrame");
      const overlay = document.getElementById("deviceFrameOverlay");
      if (toggle && overlay) {
        overlay.style.backgroundImage = `url('${config.deviceFrameUrl}')`;
        toggle.addEventListener("change", function () {
          const parent = document.getElementById("currentPreviewContainer");
          if (!parent) return;
          parent.classList.toggle("show-frame", this.checked);
        });
      }
    }

    function initApiIndicator() {
      const apiIndicator = document.getElementById("apiKeyIndicator");
      if (!apiIndicator) return;
      setTimeout(() => {
        apiIndicator.classList.add("auto-collapse");
        setTimeout(() => {
          apiIndicator.classList.remove("auto-collapse");
          apiIndicator.classList.add("collapsed");
        }, 3000);
      }, 100);
    }

    function bindModalClose() {
      window.addEventListener("click", (event) => {
        const modal = document.getElementById("scheduleModal");
        if (event.target === modal) {
          closeModal("scheduleModal");
        }
      });
    }

    function setWorkflowMode(mode) {
      workflowMode = mode;
      document.documentElement.setAttribute("data-mobile-workflow-mode", mode);
      document.querySelectorAll("[data-workflow-mode]").forEach((button) => {
        const isActive = button.dataset.workflowMode === mode;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-selected", isActive ? "true" : "false");
      });
      document.querySelectorAll("[data-workflow-panel]").forEach((panel) => {
        const isActive = panel.dataset.workflowPanel === mode;
        panel.classList.toggle("active", isActive);
        panel.setAttribute("aria-hidden", isActive ? "false" : "true");
      });
      if (mobileQuery.matches) {
        document.querySelector(".workflow-mode-bar")?.scrollIntoView({
          block: "start",
          behavior: "smooth",
        });
      }
    }

    function bindWorkflowMode() {
      document.querySelectorAll("[data-workflow-mode]").forEach((button) => {
        button.addEventListener("click", () => setWorkflowMode(button.dataset.workflowMode));
      });
      setWorkflowMode("configure");
    }

    function bindControls() {
      document.getElementById("settingsForm")?.addEventListener("submit", (event) => {
        event.preventDefault();
      });
      document.getElementById("scheduleForm")?.addEventListener("submit", (event) => {
        event.preventDefault();
      });
      document.querySelectorAll("[data-plugin-action]").forEach((button) => {
        button.addEventListener("click", () => handleAction(button.dataset.pluginAction, button));
      });
      document.querySelectorAll("[data-open-modal]").forEach((button) => {
        button.addEventListener("click", () => openModal(button.dataset.openModal));
      });
      document.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", () => closeModal(button.dataset.closeModal));
      });
      document.querySelectorAll("[data-collapsible-toggle]").forEach((button) => {
        button.addEventListener("click", () => ui.toggleCollapsible && ui.toggleCollapsible(button));
      });
      document.querySelectorAll("[data-frame-option]").forEach((option) => {
        option.addEventListener("click", () => selectedFrame(option));
        option.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            selectedFrame(option);
          }
        });
      });
      document.getElementById("showLastProgressBtn")?.addEventListener("click", showLastProgress);
      document.getElementById("closeProgressBtn")?.addEventListener("click", () => {
        setHidden(document.getElementById("requestProgress"), true);
      });
      document.getElementById("displayInstanceBtn")?.addEventListener("click", displayInstanceNow);
      document.querySelector("[data-background-upload]")?.addEventListener("change", showFileName);
      document.getElementById("removeFileButton")?.addEventListener("click", removeFile);
      document.querySelectorAll("[data-lightbox-close]").forEach((button) => {
        button.addEventListener("click", () => window.Lightbox && window.Lightbox.close());
      });
    }

    function initColorPreviews() {
      document.querySelectorAll(".color-picker").forEach((picker) => {
        const preview = document.querySelector(
          `[data-color-preview="${picker.id}"]`
        );
        if (!preview) return;
        preview.style.setProperty("--preview-color", picker.value);
        picker.addEventListener("input", () => {
          preview.style.setProperty("--preview-color", picker.value);
        });
      });

      // Combined bg+text preview for style section
      const bgPicker = document.getElementById("backgroundColor");
      const textPicker = document.getElementById("textColor");
      if (bgPicker && textPicker) {
        let combined = document.getElementById("colorCombinedPreview");
        if (!combined) {
          combined = document.createElement("span");
          combined.id = "colorCombinedPreview";
          combined.className = "color-combined-preview";
          combined.textContent = "Aa";
          const textGroup = textPicker.closest(".form-group");
          if (textGroup) textGroup.appendChild(combined);
        }
        function updateCombined() {
          combined.style.background = bgPicker.value;
          combined.style.color = textPicker.value;
        }
        updateCombined();
        bgPicker.addEventListener("input", updateCombined);
        textPicker.addEventListener("input", updateCombined);
      }
    }

    function init() {
      populateStyleSettings();
      bindControls();
      bindWorkflowMode();
      initStatusBar();
      initPreviewInteractions();
      initApiIndicator();
      initColorPreviews();
      bindModalClose();
      if (mobileQuery && typeof mobileQuery.addEventListener === "function") {
        mobileQuery.addEventListener("change", () => setWorkflowMode(workflowMode));
      }
    }

    Object.assign(window, {
      closeModal,
      displayInstanceNow,
      handleAction,
      openModal,
      refreshInstancePreview,
      refreshPreviewImage,
      removeFile,
      selectedFrame,
      showFileName,
      showLastProgress,
      toggleCollapsible: ui.toggleCollapsible,
    });

    return { init };
  }

  window.InkyPiPluginPage = { create: createPluginPage };
})();

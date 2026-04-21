(function () {
  function validateAddToPlaylistAction(action) {
    if (action !== "add_to_playlist") return true;
    const instanceInput = document.getElementById("instance");
    const instanceError = document.getElementById("instance-error");
    const name = (instanceInput?.value || "").trim();
    if (!name) {
      if (instanceInput) {
        instanceInput.setAttribute("aria-invalid", "true");
        instanceInput.focus();
      }
      if (instanceError) instanceError.textContent = "Instance name is required";
      return false;
    }
    if (!/^[A-Za-z0-9 _-]+$/.test(name)) {
      if (instanceInput) {
        instanceInput.setAttribute("aria-invalid", "true");
        instanceInput.focus();
      }
      if (instanceError) instanceError.textContent = "Instance name can only contain letters, numbers, spaces, underscores, and hyphens";
      return false;
    }
    if (instanceInput) instanceInput.setAttribute("aria-invalid", "false");
    if (instanceError) instanceError.textContent = "";
    return true;
  }

  function syncModalOpenState(ui) {
    if (ui?.syncModalOpenState) return ui.syncModalOpenState();
    const open = document.querySelector(".modal.is-open");
    document.body.classList.toggle("modal-open", !!open);
  }

  function setHidden(node, hidden) {
    if (!node) return;
    node.hidden = hidden;
    node.classList.toggle("is-hidden", hidden);
  }

  function buildProgressKey(ctx, config) {
    if (ctx?.page === "plugin") {
      const pid = ctx.pluginId || config.pluginId;
      const inst = ctx.instance || "";
      return `INKYPI_LAST_PROGRESS:plugin:${pid}:${inst || "_"}`;
    }
    return "INKYPI_LAST_PROGRESS";
  }

  function fadeSkeleton(skel) {
    if (!skel) return;
    skel.classList.add('is-hidden');
    skel.addEventListener('transitionend', () => { skel.style.display = 'none'; }, { once: true });
  }

  function showInstanceFallback(imgEl, skeleton, fallback) {
    setHidden(imgEl, true);
    setHidden(skeleton, true);
    setHidden(fallback, false);
  }

  function updateCombinedColorPreview(combined, bgPicker, textPicker) {
    combined.style.background = bgPicker.value;
    combined.style.color = textPicker.value;
  }

  function createPluginPage(config) {
    const ui = globalThis.InkyPiUI || {};
    const mobileQuery = globalThis.matchMedia ? globalThis.matchMedia("(max-width: 768px)") : { matches: false, addEventListener() {} };
    const uploadedFiles = (globalThis.uploadedFiles = globalThis.uploadedFiles || {});
    let actionInFlight = false;
    let workflowMode = "configure";

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
      } catch (e) { console.warn("Failed to save progress snapshot:", e); }
    }

    function showLastProgress() {
      try {
        const keys = [
          buildProgressKey(config.progressContext, config),
          `INKYPI_LAST_PROGRESS:plugin:${config.pluginId}:_`,
        ];
        let data = null;
        for (const key of keys) {
          const raw = localStorage.getItem(key);
          if (raw) {
            try {
              data = JSON.parse(raw);
              break;
            } catch (e) {
              console.warn("Corrupt progress data, removing key:", key, e);
              localStorage.removeItem(key);
            }
          }
        }
        const progress = document.getElementById("requestProgress");
        const textEl = document.getElementById("requestProgressText");
        const clockEl = document.getElementById("requestProgressClock");
        const elapsedEl = document.getElementById("requestProgressElapsed");
        const list = document.getElementById("requestProgressList");
        const bar = document.getElementById("requestProgressBar");
        // JTN-634: Previously, the no-data path surfaced a toast only, which
        // users (especially on Weather / AI Image where validation often
        // blocks the first Update Now attempt before any snapshot is saved)
        // reported as "no feedback". Show an empty-state inside the progress
        // block itself so the click always produces a clearly visible result
        // anchored to the "Last progress" button.
        if (!data) {
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
          if (bar) { bar.style.width = "0%"; bar.setAttribute("aria-valuenow", 0); }
          if (progress) {
            setHidden(progress, false);
            progress.style.display = "";
          }
          return;
        }
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
        // JTN-312: clear the HTML `hidden` attribute so the block is visible;
        // setting style.display alone does not override the `hidden` attribute.
        // JTN-347: also clear inline display:none left by progress.stop() —
        // otherwise the block stays invisible even after removing `hidden`.
        if (progress) {
          setHidden(progress, false);
          progress.style.display = "";
        }
      } catch (e) { console.warn("Failed to show last progress:", e); }
    }

    function renderMetaBlock(metaDiv, metaContent, info) {
      if (!metaDiv || !metaContent) return;
      metaContent.innerHTML = "";
      if (!info?.plugin_meta) {
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

    function runPluginValidation(action) {
      try {
        if (typeof globalThis.validatePluginSettings === "function") {
          return !!globalThis.validatePluginSettings(action);
        }
      } catch (e) {
        console.warn("Plugin validation threw an error:", e);
      }
      return true;
    }

    function ensurePluginFormAvailable() {
      if (
        globalThis.PluginForm &&
        typeof globalThis.PluginForm.sendForm === "function"
      ) {
        return true;
      }
      showResponseModal(
        "failure",
        "Plugin form module failed to load. Refresh and try again."
      );
      return false;
    }

    async function handleAction(action, triggerButton) {
      if (action === "add_to_playlist" && !showPluginSubtab("schedule", { reportMissing: true })) {
        return;
      }
      if (!validateAddToPlaylistAction(action)) return;

      // Validate settingsForm required fields. Use validateAllInputsDetailed so
      // the failure modal names the specific field (JTN-378) instead of a
      // generic "N fields need fixing" count.
      const settingsForm = document.getElementById("settingsForm");
      if (settingsForm && globalThis.FormValidator) {
        const result = globalThis.FormValidator.validateAllInputsDetailed(settingsForm);
        if (result.count > 0) {
          showResponseModal(
            "failure",
            globalThis.FormValidator.buildValidationMessage(result)
          );
          globalThis.FormValidator.focusFirstInvalid(settingsForm);
          return;
        }
      }

      if (action === "add_to_playlist") {
        const scheduleForm = document.getElementById("scheduleForm");
        if (scheduleForm && globalThis.FormValidator) {
          const scheduleResult = globalThis.FormValidator.validateAllInputsDetailed(scheduleForm);
          if (scheduleResult.count > 0) {
            showResponseModal(
              "failure",
              globalThis.FormValidator.buildValidationMessage(scheduleResult)
            );
            globalThis.FormValidator.focusFirstInvalid(scheduleForm);
            return;
          }
        }
      }

      if (!runPluginValidation(action)) return;
      if (!ensurePluginFormAvailable()) return;

      actionInFlight = true;
      if (triggerButton) triggerButton.disabled = true;
      try {
        await globalThis.PluginForm.sendForm({
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
        actionInFlight = false;
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
        const ts = info?.refresh_time ? new Date(info.refresh_time) : null;
        const currTime = document.getElementById("currentDisplayTime");
        if (currTime) currTime.textContent = ts ? ts.toLocaleString() : "—";
        const metaDiv = document.getElementById("pluginMeta");
        const metaContent = document.getElementById("pluginMetaContent");
        renderMetaBlock(metaDiv, metaContent, info);
      } catch (e) { console.warn("Failed to refresh preview info:", e); }
    }

    // Track the element that triggered the most-recently opened modal so focus
    // can be restored when the modal closes (WAI-ARIA best practice).
    let _lastModalTrigger = null;

    function openModal(modalId, triggerEl) {
      const modal = document.getElementById(modalId);
      if (!modal) return;
      if (triggerEl) _lastModalTrigger = triggerEl;
      modal.hidden = false;
      modal.style.display = "flex";
      modal.classList.add("is-open");
      syncModalOpenState(ui);
      // JTN-463: move focus into the modal on open
      const focusable = modal.querySelector(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusable) setTimeout(() => focusable.focus(), 0);
    }

    function closeModal(modalId) {
      const modal = document.getElementById(modalId);
      if (!modal) return;
      modal.hidden = true;
      modal.style.display = "none";
      modal.classList.remove("is-open");
      syncModalOpenState(ui);
      // Restore focus to the trigger element (WAI-ARIA best practice)
      if (_lastModalTrigger) {
        _lastModalTrigger.focus();
        _lastModalTrigger = null;
      }
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
      const file = fileInput?.files?.[0];
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
      } catch (error) { console.warn("Failed to probe image URL:", probeUrl, error); }
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

      const onPrimaryError = function () {
        const canFallback =
          primaryUrl && imageUrl === primaryUrl && fallbackUrl && fallbackUrl !== primaryUrl;
        if (canFallback) {
          this.src = `${fallbackUrl}?t=${Date.now()}`;
          this.onerror = onFallbackError;
          return;
        }
        showInstanceFallback(this, skeleton, fallback);
      };
      const onFallbackError = function () {
        showInstanceFallback(this, skeleton, fallback);
      };

      instImgEl.src = `${imageUrl}?t=${Date.now()}`;
      instImgEl.onload = () => setHidden(skeleton, true);
      instImgEl.onerror = onPrimaryError;
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
          if (previewImg.src && globalThis.Lightbox) {
            globalThis.Lightbox.open(previewImg.src, previewImg.alt);
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
            globalThis.Lightbox
          ) {
            globalThis.Lightbox.open(instanceImg.src, instanceImg.alt);
          }
        });
      }
      document.addEventListener("click", (event) => {
        const img = event.target.closest("img.lightboxable");
        if (!img || !globalThis.Lightbox || !img.src) return;
        event.preventDefault();
        globalThis.Lightbox.open(img.src, img.alt || "Preview");
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

    function collapseApiIndicator(apiIndicator) {
      apiIndicator.classList.remove("auto-collapse");
      apiIndicator.classList.add("collapsed");
    }

    function initApiIndicator() {
      const apiIndicator = document.getElementById("apiKeyIndicator");
      if (!apiIndicator) return;
      // When the indicator lives in the plugin title-stack meta row it is
      // already styled as a compact chip — skip the legacy auto-collapse
      // animation that assumed a full-width header badge (JTN-design refresh).
      if (apiIndicator.closest(".plugin-mode-row")) {
        apiIndicator.classList.remove("auto-collapse", "collapsed");
        return;
      }
      setTimeout(() => {
        apiIndicator.classList.add("auto-collapse");
        setTimeout(() => collapseApiIndicator(apiIndicator), 3000);
      }, 100);
    }

    // JTN-629: Capture a snapshot of the settings form on load so we can
    // detect unsaved changes. `formDirty` compares each input value to its
    // initial value. Files/passwords are omitted — just string values from
    // inputs/textareas/selects are enough to catch the common case (a typed
    // prompt in AI Image) without false positives from checkbox serialization.
    function getSettingsFormSnapshot() {
      const form = document.getElementById("settingsForm");
      if (!form) return null;
      const snapshot = {};
      form.querySelectorAll("input, textarea, select").forEach((el) => {
        if (!el.name && !el.id) return;
        const key = el.name || el.id;
        if (el.type === "file") return;
        if (el.type === "checkbox" || el.type === "radio") {
          snapshot[`${key}:${el.value}`] = el.checked ? "1" : "0";
        } else {
          snapshot[key] = el.value == null ? "" : String(el.value);
        }
      });
      return snapshot;
    }

    let _settingsFormSnapshot = null;

    function isSettingsFormDirty() {
      const current = getSettingsFormSnapshot();
      if (!_settingsFormSnapshot || !current) return false;
      const keys = new Set([
        ...Object.keys(_settingsFormSnapshot),
        ...Object.keys(current),
      ]);
      for (const key of keys) {
        if (_settingsFormSnapshot[key] !== current[key]) return true;
      }
      return false;
    }

    function initApiKeysLeaveGuard() {
      const links = Array.from(document.querySelectorAll("[data-api-keys-link]"));
      const modal = document.getElementById("apiKeysLeaveConfirmModal");
      if (links.length === 0 || !modal) return;
      // Snapshot AFTER the rest of init runs so schema-populated defaults are
      // captured as the baseline, not flagged as "dirty" on first click.
      setTimeout(() => {
        _settingsFormSnapshot = getSettingsFormSnapshot();
      }, 0);
      links.forEach((link) => {
        link.addEventListener("click", (event) => {
          if (!isSettingsFormDirty()) return; // fall through to normal navigation
          event.preventDefault();
          const confirmBtn = document.getElementById("confirmApiKeysLeaveBtn");
          if (confirmBtn && link.href) confirmBtn.href = link.href;
          openModal("apiKeysLeaveConfirmModal", link);
        });
      });
      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        if (modal.hidden) return;
        event.preventDefault();
        closeModal("apiKeysLeaveConfirmModal");
      });
      globalThis.addEventListener("click", (event) => {
        if (event.target === modal) closeModal("apiKeysLeaveConfirmModal");
      });
    }

    function bindModalClose() {
      globalThis.addEventListener("click", (event) => {
        if (actionInFlight) return;
        const modal = document.getElementById("scheduleModal");
        if (event.target === modal) {
          closeModal("scheduleModal");
        }
      });
      // JTN-461: close #scheduleModal when Escape is pressed
      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        const modal = document.getElementById("scheduleModal");
        if (!modal || modal.hidden) return;
        event.preventDefault();
        closeModal("scheduleModal");
      });
    }

    // JTN design refresh: the Configure/Preview mode bar was removed in favor
    // of always showing both panels side-by-side on desktop and stacked on
    // mobile. setWorkflowMode is kept as a no-op to preserve the existing
    // public surface; callers no longer change the visible panel.
    function setWorkflowMode(mode) {
      workflowMode = mode;
      document.documentElement.setAttribute("data-mobile-workflow-mode", mode);
      document.querySelectorAll("[data-workflow-panel]").forEach((panel) => {
        panel.classList.add("active");
        panel.setAttribute("aria-hidden", "false");
        panel.removeAttribute("inert");
      });
    }

    function bindWorkflowMode() {
      // Both panels are always visible; no buttons to bind.
      setWorkflowMode("configure");
    }

    /**
     * Toggle visibility of the Configure / Style / Schedule sub-panels.
     * Mirrors the React `tabline` design from the UI handoff (JTN design refresh).
     */
    function setPluginSubtab(id) {
      document.querySelectorAll("[data-plugin-subtab]").forEach((btn) => {
        const active = btn.dataset.pluginSubtab === id;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-selected", active ? "true" : "false");
      });
      document.querySelectorAll("[data-plugin-subpanel]").forEach((panel) => {
        const active = panel.dataset.pluginSubpanel === id;
        panel.hidden = !active;
      });
    }

    function bindPluginSubtabs() {
      const buttons = document.querySelectorAll("[data-plugin-subtab]");
      if (!buttons.length) return;
      buttons.forEach((btn) => {
        btn.addEventListener("click", () => setPluginSubtab(btn.dataset.pluginSubtab));
      });
      setPluginSubtab("configure");
    }

    function showPluginSubtab(id, { focus = false, reportMissing = false } = {}) {
      const panel = document.querySelector(`[data-plugin-subpanel="${id}"]`);
      if (!panel) {
        if (reportMissing) {
          showResponseModal(
            "failure",
            "Unable to open scheduling controls. Please refresh the page and try again."
          );
        }
        return false;
      }
      setPluginSubtab(id);
      try {
        const scrollTarget = document.getElementById("scheduleForm") || panel;
        scrollTarget.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (_) {
        /* noop */
      }
      if (focus) {
        const focusTarget =
          panel.querySelector("[data-subtab-focus-target]") ||
          panel.querySelector(
            'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])'
          );
        if (focusTarget) setTimeout(() => focusTarget.focus(), 0);
      }
      return true;
    }

    function bindControls() {
      // JTN-648: route Enter-key implicit submit through the app-level
      // validator so empty required fields surface the same labelled toast
      // ("<Field> is required") as the Update Preview click path. The form
      // carries `novalidate` so native HTML5 bubbles never appear.
      document.getElementById("settingsForm")?.addEventListener("submit", (event) => {
        event.preventDefault();
        const settingsForm = event.currentTarget;
        if (settingsForm && globalThis.FormValidator) {
          const result = globalThis.FormValidator.validateAllInputsDetailed(settingsForm);
          if (result.count > 0) {
            showResponseModal(
              "failure",
              globalThis.FormValidator.buildValidationMessage(result)
            );
            globalThis.FormValidator.focusFirstInvalid(settingsForm);
          }
        }
      });
      document.getElementById("scheduleForm")?.addEventListener("submit", (event) => {
        event.preventDefault();
      });
      document.querySelectorAll("[data-plugin-action]").forEach((button) => {
        button.addEventListener("click", () => handleAction(button.dataset.pluginAction, button));
      });
      document.querySelectorAll("[data-plugin-subtab-target]").forEach((button) => {
        button.addEventListener("click", (event) => {
          if (button.disabled || button.getAttribute("aria-disabled") === "true") return;
          const ok = showPluginSubtab(button.dataset.pluginSubtabTarget, {
            focus: true,
            reportMissing: true,
          });
          if (!ok) event.preventDefault();
        });
      });
      document.addEventListener("click", (event) => {
        const opener = event.target.closest("[data-open-modal]");
        if (opener) openModal(opener.dataset.openModal, opener);
      });
      // JTN-633: the DRAFT-state "Add to Playlist" button now routes into the
      // inline Schedule tab. Keep a direct safeguard so the click can never
      // silently no-op — if the schedule panel ever goes missing, the user
      // gets clear feedback instead of nothing happening.
      document.querySelectorAll('[data-plugin-draft="true"][data-plugin-subtab-target]').forEach((button) => {
        button.addEventListener("click", (event) => {
          if (button.disabled || button.getAttribute("aria-disabled") === "true") return;
          const ok = showPluginSubtab(button.dataset.pluginSubtabTarget, {
            focus: true,
            reportMissing: true,
          });
          if (!ok) event.preventDefault();
        });
      });
      document.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", () => closeModal(button.dataset.closeModal));
      });
      // Collapsible toggle is bound via delegation in ui_helpers.js so every
      // `[data-collapsible-toggle]` button updates aria-expanded consistently.
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
      // Persistent progress card: render whatever the last snapshot is
      // (or the empty-state) on first load so the aside card always has content.
      try { showLastProgress(); } catch (_) { /* noop */ }
      document.getElementById("displayInstanceBtn")?.addEventListener("click", displayInstanceNow);
      document.querySelector("[data-background-upload]")?.addEventListener("change", showFileName);
      document.getElementById("removeFileButton")?.addEventListener("click", removeFile);
      document.querySelectorAll("[data-lightbox-close]").forEach((button) => {
        button.addEventListener("click", () => globalThis.Lightbox?.close());
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
        updateCombinedColorPreview(combined, bgPicker, textPicker);
        bgPicker.addEventListener("input", () => updateCombinedColorPreview(combined, bgPicker, textPicker));
        textPicker.addEventListener("input", () => updateCombinedColorPreview(combined, bgPicker, textPicker));
      }
    }

    function init() {
      populateStyleSettings();
      bindControls();
      const scheduleForm = document.getElementById("scheduleForm");
      if (scheduleForm && globalThis.FormValidator?.initFormValidation) {
        globalThis.FormValidator.initFormValidation(scheduleForm);
      }
      bindWorkflowMode();
      bindPluginSubtabs();
      initStatusBar();
      initPreviewInteractions();
      initApiIndicator();
      initApiKeysLeaveGuard();
      initColorPreviews();
      bindModalClose();
      if (mobileQuery && typeof mobileQuery.addEventListener === "function") {
        mobileQuery.addEventListener("change", () => setWorkflowMode(workflowMode));
      }
    }

    Object.assign(globalThis, {
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

  globalThis.InkyPiPluginPage = { create: createPluginPage };
})();

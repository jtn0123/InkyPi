(function () {
  function normalizeValue(value) {
    if (value == null) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value);
  }

  function parseJson(value, fallback) {
    try {
      return JSON.parse(value);
    } catch (error) {
      // Intentionally ignored — invalid JSON returns the provided fallback value
      return fallback;
    }
  }

  function getFieldValue(root, fieldName) {
    const radios = root.querySelectorAll(`input[type="radio"][name="${fieldName}"]`);
    if (radios.length) {
      const checked = Array.from(radios).find((input) => input.checked);
      return checked ? normalizeValue(checked.value) : "";
    }

    const checkboxes = root.querySelectorAll(`input[type="checkbox"][name="${fieldName}"]`);
    if (checkboxes.length) {
      const primary = Array.from(checkboxes).find((input) => input.dataset.checkboxPrimary === "true") || checkboxes[0];
      return primary.checked ? normalizeValue(primary.value || "true") : "false";
    }

    const field = root.querySelector(`[name="${fieldName}"]`);
    return field ? normalizeValue(field.value) : "";
  }

  function setHiddenState(node, hidden) {
    node.hidden = hidden;
    node.classList.toggle("hidden", hidden);
    node.querySelectorAll("input, select, textarea, button").forEach((control) => {
      if (control.type === "hidden") return;
      if (hidden) {
        control.dataset.wasDisabled = control.disabled ? "true" : "false";
        control.disabled = true;
      } else if (control.dataset.wasDisabled !== "true") {
        control.disabled = false;
      }
    });
  }

  function matchesVisibility(node, root) {
    const fieldName = node.dataset.visibleIfField;
    if (!fieldName) return true;
    const operator = node.dataset.visibleIfOperator || "equals";
    const expected = node.dataset.visibleIfEquals || "";
    const values = parseJson(node.dataset.visibleIfValues || "[]", []);
    const actual = getFieldValue(root, fieldName);

    if (operator === "equals") return actual === expected;
    if (operator === "not_equals") return actual !== expected;
    if (operator === "not_empty") return actual.trim() !== "";
    if (operator === "in") return values.map(normalizeValue).includes(actual);
    return true;
  }

  function applyVisibility(root) {
    root.querySelectorAll("[data-visible-if-field]").forEach((node) => {
      setHiddenState(node, !matchesVisibility(node, root));
    });
  }

  function replaceOptions(select, options, currentValue) {
    const previous = currentValue || select.dataset.currentValue || select.value;
    while (select.firstChild) select.removeChild(select.firstChild);
    options.forEach((opt) => {
      const option = document.createElement("option");
      option.value = opt.value;
      option.textContent = opt.label;
      if (normalizeValue(previous) === normalizeValue(opt.value)) {
        option.selected = true;
      }
      select.appendChild(option);
    });
    if (select.selectedIndex === -1 && select.options.length) {
      select.options[0].selected = true;
    }
  }

  function applyDependentOptions(root) {
    root.querySelectorAll("select[data-options-source-field]").forEach((select) => {
      const optionMap = parseJson(select.dataset.optionsMap || "{}", {});
      const fallbackOptions = parseJson(select.dataset.fallbackOptions || "[]", []);
      const sourceValue = getFieldValue(root, select.dataset.optionsSourceField);
      const options = optionMap[sourceValue] || fallbackOptions;
      replaceOptions(select, options, select.dataset.currentValue || select.value);
    });
  }

  function syncCheckboxState(root) {
    root.querySelectorAll("input[type='checkbox'].toggle-checkbox").forEach((checkbox) => {
      checkbox.dataset.checkboxPrimary = "true";
      checkbox.value = checkbox.checked ? checkbox.value || "true" : checkbox.dataset.uncheckedValue || "true";
    });
  }

  function bindStandardEvents(root) {
    root.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (
        typeof target.matches === "function" &&
        target.matches("input[type='checkbox'].toggle-checkbox")
      ) {
        target.value = target.checked ? target.dataset.checkedValue || "true" : target.dataset.uncheckedValue || "true";
      }
      if (
        (typeof target.matches === "function" &&
          target.matches("input, select, textarea")) ||
        (typeof target.closest === "function" &&
          target.closest("input, select, textarea"))
      ) {
        applyDependentOptions(root);
        applyVisibility(root);
      }
    });
  }

  function createHiddenInput(name, value) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    return input;
  }

  function initClockFacePicker(widget, config) {
    const hidden = widget.querySelector("#selected-clock-face");
    const primary = widget.querySelector("[name='primaryColor']");
    const secondary = widget.querySelector("[name='secondaryColor']");
    const options = Array.from(widget.querySelectorAll(".image-option"));
    if (!hidden || !primary || !secondary || !options.length) return;

    const selectOption = (option) => {
      options.forEach((item) => item.classList.toggle("selected", item === option));
      hidden.value = option.dataset.faceName || "";
      if (option.dataset.primaryColor) primary.value = option.dataset.primaryColor;
      if (option.dataset.secondaryColor) secondary.value = option.dataset.secondaryColor;
    };

    options.forEach((option) => {
      option.addEventListener("click", () => selectOption(option));
    });

    const currentValue = config.selectedClockFace || hidden.value;
    const initial = options.find((option) => option.dataset.faceName === currentValue) || options[0];
    selectOption(initial);

    if (config.primaryColor) primary.value = config.primaryColor;
    if (config.secondaryColor) secondary.value = config.secondaryColor;
  }

  function initNewspaperSearch(widget, config) {
    const newspapers = parseJson(widget.dataset.newspapers || "[]", []);
    const newspaperInput = widget.querySelector("#newspaper");
    const locationInput = widget.querySelector("#locationSearch");
    const slugInput = widget.querySelector("#newspaperSlug");
    const newspaperList = widget.querySelector("#newspaperList");
    if (!newspaperInput || !locationInput || !slugInput || !newspaperList) return;

    const renderList = (items) => {
      while (newspaperList.firstChild) newspaperList.removeChild(newspaperList.firstChild);
      items.forEach((paper) => {
        const option = document.createElement("option");
        option.value = paper.name;
        newspaperList.appendChild(option);
      });
    };

    const updateSlugAndLocation = () => {
      const selected = newspapers.find((paper) => paper.name === newspaperInput.value);
      if (selected) {
        slugInput.value = selected.slug;
        locationInput.value = `${selected.city}, ${selected.country}`;
      } else {
        slugInput.value = "";
      }
    };

    const filterByLocation = () => {
      const value = locationInput.value.toLowerCase();
      const filtered = newspapers.filter((paper) => {
        const formatted = `${paper.city}, ${paper.country}`.toLowerCase();
        return !value || formatted.includes(value);
      });
      renderList(filtered);
      const selected = newspapers.find((paper) => paper.name === newspaperInput.value);
      if (!selected) slugInput.value = "";
    };

    newspaperInput.addEventListener("change", updateSlugAndLocation);
    locationInput.addEventListener("change", filterByLocation);
    renderList(newspapers);

    if (config.newspaperName) {
      newspaperInput.value = config.newspaperName;
      updateSlugAndLocation();
    }
  }

  function createCalendarEntry(url, color) {
    const entry = document.createElement("div");
    entry.className = "dynamic-list-item compact-repeater compact-repeater-calendar";

    const toolbar = document.createElement("div");
    toolbar.className = "dynamic-list-toolbar compact-repeater-toolbar";
    const urlInput = document.createElement("input");
    urlInput.type = "text";
    urlInput.name = "calendarURLs[]";
    urlInput.className = "form-input";
    urlInput.placeholder = "https://calendar.google.com/…/basic.ics";
    urlInput.required = true;
    urlInput.value = url || "";
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "remove-btn icon-button";
    removeBtn.setAttribute("aria-label", "Remove calendar");
    const icon = document.createElement("i");
    icon.className = "ph ph-trash ph-thin action-icon";
    icon.setAttribute("aria-hidden", "true");
    removeBtn.appendChild(icon);
    removeBtn.addEventListener("click", () => {
      const list = entry.parentElement;
      entry.remove();
      updateRepeaterEmptyState(list);
    });
    toolbar.appendChild(urlInput);
    toolbar.appendChild(removeBtn);

    const colorLabel = document.createElement("label");
    colorLabel.className = "dynamic-list-color-group";
    const colorSpan = document.createElement("span");
    colorSpan.textContent = "Color";
    const colorInput = document.createElement("input");
    colorInput.type = "color";
    colorInput.name = "calendarColors[]";
    colorInput.className = "color-picker";
    colorInput.value = color || "#007BFF";
    colorLabel.appendChild(colorSpan);
    colorLabel.appendChild(colorInput);

    entry.appendChild(toolbar);
    entry.appendChild(colorLabel);
    return entry;
  }

  function updateRepeaterEmptyState(list) {
    const items = list.querySelectorAll(".dynamic-list-item").length;
    let msg = list.querySelector(".empty-state-message");
    if (items === 0 && !msg) {
      msg = document.createElement("p");
      msg.className = "empty-state-message";
      msg.textContent = 'No calendars configured. Click "Add Calendar" to get started.';
      list.appendChild(msg);
    } else if (items > 0 && msg) {
      msg.remove();
    }
  }

  function handleRemoveClick(button, list) {
    if (list.querySelectorAll(".dynamic-list-item").length <= 1) {
      const item = button.closest(".dynamic-list-item");
      if (item) {
        item.classList.add("shake");
        item.addEventListener("animationend", () => item.classList.remove("shake"), { once: true });
      }
      return;
    }
    const item = button.closest(".dynamic-list-item");
    const parentList = item?.parentElement;
    item?.remove();
    if (parentList) updateRepeaterEmptyState(parentList);
  }

  function bindRemoveButtons(list) {
    list.querySelectorAll(".remove-btn").forEach((button) => {
      if (button.dataset.boundRemove === "true") return;
      button.dataset.boundRemove = "true";
      button.addEventListener("click", () => handleRemoveClick(button, list));
    });
  }

  function initCalendarRepeater(widget, config) {
    const list = widget.querySelector("[data-repeater-list]");
    const addButton = widget.querySelector("[data-repeater-add]");
    if (!list || !addButton) return;
    bindRemoveButtons(list);
    if (!list.children.length) {
      const urls = config["calendarURLs[]"] || [""];
      const colors = config["calendarColors[]"] || ["#007BFF"];
      urls.forEach((url, index) => list.appendChild(createCalendarEntry(url, colors[index] || "#007BFF")));
      if (!urls.length) list.appendChild(createCalendarEntry("", "#007BFF"));
    }
    updateRepeaterEmptyState(list);
    addButton.addEventListener("click", () => {
      list.appendChild(createCalendarEntry("", "#007BFF"));
      updateRepeaterEmptyState(list);
    });
  }

  function createTodoEntry(title, body) {
    const entry = document.createElement("div");
    entry.className = "dynamic-list-item compact-repeater compact-repeater-text";

    const toolbar = document.createElement("div");
    toolbar.className = "dynamic-list-toolbar compact-repeater-toolbar";
    const titleInput = document.createElement("input");
    titleInput.type = "text";
    titleInput.name = "list-title[]";
    titleInput.className = "form-input";
    titleInput.placeholder = "List title";
    titleInput.value = title || "";
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "remove-btn icon-button";
    removeBtn.setAttribute("aria-label", "Remove list");
    const icon = document.createElement("i");
    icon.className = "ph ph-trash ph-thin action-icon";
    icon.setAttribute("aria-hidden", "true");
    removeBtn.appendChild(icon);
    removeBtn.addEventListener("click", () => entry.remove());
    toolbar.appendChild(titleInput);
    toolbar.appendChild(removeBtn);

    const textarea = document.createElement("textarea");
    textarea.name = "list[]";
    textarea.className = "form-input dynamic-list-textarea";
    textarea.rows = 5;
    textarea.placeholder = "Enter tasks, one per line";
    textarea.value = body || "";

    entry.appendChild(toolbar);
    entry.appendChild(textarea);
    return entry;
  }

  function initTodoRepeater(widget, config) {
    const list = widget.querySelector("[data-repeater-list]");
    const addButton = widget.querySelector("[data-repeater-add]");
    const maxItems = Number(list?.dataset.maxItems || widget.dataset.maxItems || "3");
    if (!list || !addButton) return;
    bindRemoveButtons(list);
    if (!list.children.length) {
      const titles = config["list-title[]"] || [];
      const items = config["list[]"] || [];
      const seedCount = Math.min(Math.max(titles.length, items.length, 1), maxItems);
      for (let index = 0; index < seedCount; index += 1) {
        list.appendChild(createTodoEntry(titles[index] || "", items[index] || ""));
      }
    }
    addButton.addEventListener("click", () => {
      if (list.children.length < maxItems) {
        list.appendChild(createTodoEntry("", ""));
      }
    });
  }

  function initGitHubColors(widget, config) {
    const defaults = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"];
    const colors = config["contributionColor[]"] || defaults;
    widget.querySelectorAll("input[name='contributionColor[]']").forEach((input, index) => {
      input.value = colors[index] || defaults[index];
    });
  }

  function initImageUpload(widget, config) {
    const fileInput = widget.querySelector("#imageUpload");
    const fileNames = widget.querySelector("#fileNames");
    const hiddenContainer = widget.querySelector("#hiddenFileInputs");
    if (!fileInput || !fileNames || !hiddenContainer) return;

    const uploadedFiles = globalThis.__INKYPI_UPLOADED_FILES__ || (globalThis.__INKYPI_UPLOADED_FILES__ = {});
    if (!uploadedFiles["imageFiles[]"]) uploadedFiles["imageFiles[]"] = [];

    const renderFile = (id, fileName, removeHandler) => {
      const row = document.createElement("div");
      row.className = "file-name";
      row.id = id;
      const span = document.createElement("span");
      span.textContent = fileName;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "remove-btn";
      btn.setAttribute("aria-label", "Remove file");
      btn.textContent = "X";
      btn.addEventListener("click", removeHandler);
      row.appendChild(span);
      row.appendChild(btn);
      fileNames.appendChild(row);
    };

    (config["imageFiles[]"] || []).forEach((filePath) => {
      const fileName = filePath.split("/").pop();
      renderFile(`existing-${fileName}`, fileName, () => {
        const row = widget.querySelector(`#existing-${CSS.escape(fileName)}`);
        if (row) row.remove();
        const hidden = widget.querySelector(`#hidden-${CSS.escape(fileName)}`);
        if (hidden) hidden.remove();
      });
      const hidden = createHiddenInput("imageFiles[]", filePath);
      hidden.id = `hidden-${fileName}`;
      hiddenContainer.appendChild(hidden);
    });

    fileInput.addEventListener("change", () => {
      Array.from(fileInput.files || []).forEach((file) => {
        if (uploadedFiles["imageFiles[]"].some((item) => item.name === file.name)) return;
        uploadedFiles["imageFiles[]"].push(file);
        renderFile(`added-${file.name}`, file.name, () => {
          uploadedFiles["imageFiles[]"] = uploadedFiles["imageFiles[]"].filter((item) => item.name !== file.name);
          const row = widget.querySelector(`#added-${CSS.escape(file.name)}`);
          if (row) row.remove();
        });
      });
      fileInput.value = "";
    });
  }

  function initWeatherMap(widget, config) {
    const latInput = widget.querySelector("#latitude");
    const lonInput = widget.querySelector("#longitude");
    const openButton = widget.querySelector("#openMap");
    const saveButton = widget.querySelector("#closeMap");
    const modal = widget.querySelector("#mapModal");
    const mapRoot = widget.querySelector("#map");
    if (!latInput || !lonInput || !openButton || !saveButton || !modal || !mapRoot) return;

    latInput.value = config.latitude || latInput.value || "40.7128";
    lonInput.value = config.longitude || lonInput.value || "-74.0060";

    let map;
    let marker;

    const openModal = () => {
      modal.style.display = "block";
      setTimeout(() => {
        if (!globalThis.L || map) return;
        const lat = Number.parseFloat(latInput.value) || 40.7128;
        const lon = Number.parseFloat(lonInput.value) || -74.0060;
        map = globalThis.L.map(mapRoot).setView([lat, lon], 4.5);
        globalThis.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);
        marker = globalThis.L.marker([lat, lon], { draggable: true }).addTo(map);
        map.on("click", (event) => marker.setLatLng(event.latlng));
      }, 100);
    };

    const closeModal = () => {
      if (marker) {
        const position = marker.getLatLng().wrap();
        latInput.value = position.lat;
        lonInput.value = position.lng;
      }
      modal.style.display = "none";
    };

    openButton.addEventListener("click", openModal);
    saveButton.addEventListener("click", closeModal);
    modal.querySelector(".close-button")?.addEventListener("click", closeModal);
  }

  const widgetInitializers = {
    "clock-face-picker": initClockFacePicker,
    "newspaper-search": initNewspaperSearch,
    "calendar-repeater": initCalendarRepeater,
    "todo-repeater": initTodoRepeater,
    "github-colors": initGitHubColors,
    "image-upload-list": initImageUpload,
    "weather-map": initWeatherMap,
  };

  function initializeWidgets(root, config) {
    root.querySelectorAll("[data-hybrid-widget]").forEach((widget) => {
      const widgetType = widget.dataset.hybridWidget;
      const widgetConfig = parseJson(widget.dataset.widgetConfig || "{}", {});
      const initializer = widgetInitializers[widgetType];
      if (initializer) initializer(widget, { ...config, ...widgetConfig });
    });
  }

  function init() {
    const root = document.querySelector("[data-settings-schema]");
    if (!root) return;
    const boot = globalThis.__INKYPI_PLUGIN_BOOT__ || {};
    syncCheckboxState(root);
    initializeWidgets(root, boot.pluginSettings || {});
    applyDependentOptions(root);
    applyVisibility(root);
    bindStandardEvents(root);
  }

  globalThis.InkyPiPluginSchema = { init };
  document.addEventListener("DOMContentLoaded", init);
})();

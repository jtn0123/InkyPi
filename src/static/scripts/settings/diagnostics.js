(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  const STAGE_LABELS = {
    request_ms: "Request",
    generate_ms: "Generate",
    preprocess_ms: "Preprocess",
    display_ms: "Display",
  };

  const PLUGIN_AVG_LABELS = {
    request_avg: "Request",
    generate_avg: "Generate",
    display_avg: "Display",
  };

  function formatMs(val) {
    if (val === null || val === undefined) return "—";
    const seconds = val / 1000;
    return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
  }

  function formatPercent(val) {
    if (val === null || val === undefined || Number.isNaN(Number(val))) {
      return "—";
    }
    return `${Number(val).toFixed(1)}%`;
  }

  function formatDiskFree(val) {
    if (val === null || val === undefined || Number.isNaN(Number(val))) {
      return "—";
    }
    return `${Number(val).toFixed(1)} GB free`;
  }

  function formatUptime(seconds) {
    if (
      seconds === null ||
      seconds === undefined ||
      Number.isNaN(Number(seconds))
    ) {
      return "—";
    }
    const total = Math.floor(Number(seconds));
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const mins = Math.floor((total % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h ${mins}m`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  }

  const SYSTEM_HEALTH_ROWS = [
    { key: "cpu_percent", label: "CPU", formatter: formatPercent },
    { key: "memory_percent", label: "Memory", formatter: formatPercent },
    { key: "disk_free_gb", label: "Disk", formatter: formatDiskFree },
    { key: "uptime_seconds", label: "Uptime", formatter: formatUptime },
  ];

  function buildTable(headers) {
    const table = document.createElement("table");
    table.className = "bench-table";
    const thead = document.createElement("thead");
    const row = document.createElement("tr");
    for (const header of headers) {
      const cell = document.createElement("th");
      cell.textContent = header;
      row.appendChild(cell);
    }
    thead.appendChild(row);
    table.appendChild(thead);
    return table;
  }

  function appendCell(row, text) {
    const cell = document.createElement("td");
    cell.textContent = text;
    row.appendChild(cell);
  }

  function buildSummaryTable(summaryData) {
    const table = buildTable(["Stage", "p50", "p95"]);
    table.className = "bench-table";
    const tbody = document.createElement("tbody");
    for (const [key, label] of Object.entries(STAGE_LABELS)) {
      const row = document.createElement("tr");
      const stage = summaryData?.[key] || {};
      appendCell(row, label);
      appendCell(row, formatMs(stage.p50));
      appendCell(row, formatMs(stage.p95));
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    return table;
  }

  function buildPluginsTable(items) {
    const table = buildTable(["Plugin", "Runs"].concat(Object.values(PLUGIN_AVG_LABELS)));
    table.className = "bench-table";
    const tbody = document.createElement("tbody");
    for (const item of items.slice(0, 10)) {
      const row = document.createElement("tr");
      appendCell(row, item.plugin_id || "—");
      appendCell(row, String(item.runs || 0));
      for (const key of Object.keys(PLUGIN_AVG_LABELS)) {
        appendCell(row, formatMs(item[key]));
      }
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    return table;
  }

  function buildSystemHealthTable(systemData) {
    const table = buildTable(["Metric", "Value"]);
    table.className = "bench-table";
    const tbody = document.createElement("tbody");
    for (const spec of SYSTEM_HEALTH_ROWS) {
      const row = document.createElement("tr");
      appendCell(row, spec.label);
      appendCell(row, spec.formatter(systemData?.[spec.key]));
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    return table;
  }

  function normalizePluginHealthStatus(info) {
    if (typeof info === "string") return info;
    if (!info || typeof info !== "object") return "—";
    if (info.status || info.state) {
      return info.status || info.state;
    }
    return info.ok === false ? "error" : "ok";
  }

  function getPluginHealthEntries(items) {
    if (Array.isArray(items)) {
      return items.map((item) => [
        item.plugin_id || "—",
        item.status || item.state || "—",
      ]);
    }
    return Object.entries(items || {}).map(([pluginId, info]) => [
      pluginId,
      normalizePluginHealthStatus(info),
    ]);
  }

  function buildPluginHealthTable(items) {
    const table = buildTable(["Plugin", "Status"]);
    table.className = "bench-table";
    const tbody = document.createElement("tbody");
    const entries = getPluginHealthEntries(items);
    if (entries.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 2;
      cell.textContent = "No plugin health data";
      row.appendChild(cell);
      tbody.appendChild(row);
    } else {
      for (const [pluginId, status] of entries) {
        const row = document.createElement("tr");
        appendCell(row, pluginId);
        appendCell(row, status);
        tbody.appendChild(row);
      }
    }
    table.appendChild(tbody);
    return table;
  }

  function buildIsolationTable(isolationData) {
    const isolatedPlugins = Array.isArray(isolationData?.isolated_plugins)
      ? isolationData.isolated_plugins
      : [];
    if (isolatedPlugins.length === 0) {
      const msg = document.createElement("div");
      msg.className = "bench-empty";
      msg.textContent = "No plugins isolated";
      return msg;
    }
    const table = buildTable(["Plugin", "Isolated"]);
    table.className = "bench-table";
    const tbody = document.createElement("tbody");
    for (const pluginId of isolatedPlugins) {
      const row = document.createElement("tr");
      appendCell(row, pluginId);
      appendCell(row, "Yes");
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    return table;
  }

  function setPanelFailure(panelId, message, error) {
    console.warn(message, error);
    const panel = document.getElementById(panelId);
    if (panel) {
      panel.textContent = message;
    }
  }

  function getIsolationFailureMessage(data, verb, pluginId) {
    const fallbackMsg = `Failed to ${verb} plugin`;
    let errorText = fallbackMsg;
    if (typeof data?.error === "string") {
      errorText = data.error;
    } else if (data?.error != null) {
      errorText = String(data.error);
    }
    if (errorText.includes("registered")) {
      return `Plugin "${pluginId}" is not a registered plugin. Check the ID and try again.`;
    }
    return errorText;
  }

  function createDiagnosticsModule({ ui }) {
    let progressES = null;

    async function refreshBenchmarks() {
      ui.setPanelLoading?.("benchSummary", true);
      try {
        const [summaryResp, pluginsResp] = await Promise.all([
          fetch("/api/benchmarks/summary?window=24h", { cache: "no-store" }),
          fetch("/api/benchmarks/plugins?window=24h", { cache: "no-store" }),
        ]);
        const summary = await summaryResp.json();
        const plugins = await pluginsResp.json();

        const panel = document.getElementById("benchSummary");
        if (!panel) return;
        panel.textContent = "";

        const summaryData = summary.summary || {};
        const hasData = Object.values(summaryData).some(
          (stage) => stage?.p50 !== null && stage?.p50 !== undefined
        );
        const pluginItems = Array.isArray(plugins?.items) ? plugins.items : [];

        if (!hasData && pluginItems.length === 0) {
          const emptyMsg = document.createElement("div");
          emptyMsg.className = "bench-empty";
          emptyMsg.textContent =
            "No benchmark data recorded in the last 24 hours. Benchmarks are collected automatically on each display refresh.";
          panel.appendChild(emptyMsg);
          return;
        }

        const heading1 = document.createElement("strong");
        heading1.textContent = "Benchmark Summary (24h)";
        panel.appendChild(heading1);
        panel.appendChild(buildSummaryTable(summaryData));

        if (pluginItems.length > 0) {
          const heading2 = document.createElement("strong");
          heading2.textContent = "Per-plugin Averages";
          panel.appendChild(heading2);
          panel.appendChild(buildPluginsTable(pluginItems));
        }
      } catch (e) {
        setPanelFailure("benchSummary", "Failed to load benchmark summary", e);
      } finally {
        ui.setPanelLoading?.("benchSummary", false);
      }
    }

    async function refreshHealth() {
      ui.setPanelLoading?.("healthSummary", true);
      try {
        const [pluginsResp, systemResp] = await Promise.all([
          fetch("/api/health/plugins", { cache: "no-store" }),
          fetch("/api/health/system", { cache: "no-store" }),
        ]);
        const plugins = await pluginsResp.json();
        const system = await systemResp.json();

        const panel = document.getElementById("healthSummary");
        if (!panel) return;
        panel.textContent = "";

        const heading1 = document.createElement("strong");
        heading1.textContent = "System Health";
        panel.appendChild(heading1);
        panel.appendChild(buildSystemHealthTable(system || {}));

        const heading2 = document.createElement("strong");
        heading2.textContent = "Plugin Health";
        panel.appendChild(heading2);
        panel.appendChild(buildPluginHealthTable(plugins.items || {}));
      } catch (e) {
        setPanelFailure("healthSummary", "Failed to load health data", e);
      } finally {
        ui.setPanelLoading?.("healthSummary", false);
      }
    }

    async function refreshIsolation() {
      ui.setPanelLoading?.("isolationSummary", true);
      try {
        const resp = await fetch("/settings/isolation", { cache: "no-store" });
        const data = await resp.json();
        const panel = document.getElementById("isolationSummary");
        if (!panel) return;
        panel.textContent = "";
        panel.appendChild(buildIsolationTable(data || {}));
      } catch (e) {
        setPanelFailure("isolationSummary", "Failed to load isolation list", e);
      } finally {
        ui.setPanelLoading?.("isolationSummary", false);
      }
    }

    async function toggleIsolation(method, verb) {
      const pluginId = document
        .getElementById("isolatePluginInput")
        ?.value?.trim();
      if (!pluginId) {
        showResponseModal("failure", `Enter a plugin ID to ${verb}.`);
        return;
      }
      try {
        const resp = await fetch("/settings/isolation", {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plugin_id: pluginId }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showResponseModal(
            "failure",
            getIsolationFailureMessage(data, verb, pluginId)
          );
          return;
        }
        const past = verb === "isolate" ? "isolated" : "un-isolated";
        showResponseModal("success", `Plugin "${pluginId}" has been ${past}.`);
        await refreshIsolation();
        await refreshHealth();
      } catch (e) {
        console.warn(`Failed to ${verb} plugin:`, e);
        showResponseModal(
          "failure",
          `Failed to ${verb} plugin. Check your connection and try again.`
        );
      }
    }

    async function isolatePlugin() {
      return toggleIsolation("POST", "isolate");
    }

    async function unIsolatePlugin() {
      return toggleIsolation("DELETE", "un-isolate");
    }

    async function safeReset() {
      try {
        const resp = await fetch("/settings/safe_reset", { method: "POST" });
        const data = await resp.json();
        if (resp.ok && data.success) {
          showResponseModal("success", data.message || "Safe reset complete");
          await refreshHealth();
        } else {
          showResponseModal("failure", data.error || "Safe reset failed");
        }
      } catch (e) {
        console.warn("Safe reset failed:", e);
        showResponseModal("failure", "Safe reset failed");
      }
    }

    function initProgressSSE() {
      try {
        if (!globalThis.EventSource || progressES) return;
        progressES = new EventSource("/api/progress/stream");
        const refresh = () => refreshHealth();
        progressES.addEventListener("done", refresh);
        progressES.addEventListener("error", () => {
          refresh();
          if (progressES?.readyState === globalThis.EventSource.CLOSED) {
            stopProgressSSE();
          }
        });
      } catch (e) {
        console.warn("Progress SSE unavailable:", e);
      }
    }

    function stopProgressSSE() {
      if (progressES) {
        progressES.close();
        progressES = null;
      }
    }

    function teardown() {
      stopProgressSSE();
    }

    function bind() {
      document
        .getElementById("refreshBenchmarksBtn")
        ?.addEventListener("click", refreshBenchmarks);
      document.getElementById("safeResetBtn")?.addEventListener("click", safeReset);
      document
        .getElementById("isolatePluginBtn")
        ?.addEventListener("click", isolatePlugin);
      document
        .getElementById("unIsolatePluginBtn")
        ?.addEventListener("click", unIsolatePlugin);
      document
        .getElementById("refreshIsolationBtn")
        ?.addEventListener("click", refreshIsolation);
    }

    return {
      bind,
      buildIsolationTable,
      buildPluginHealthTable,
      buildPluginsTable,
      buildSummaryTable,
      buildSystemHealthTable,
      formatDiskFree,
      formatMs,
      formatPercent,
      formatUptime,
      initProgressSSE,
      isolatePlugin,
      refreshBenchmarks,
      refreshHealth,
      refreshIsolation,
      safeReset,
      stopProgressSSE,
      teardown,
      unIsolatePlugin,
    };
  }

  settingsModules.createDiagnosticsModule = createDiagnosticsModule;
})();

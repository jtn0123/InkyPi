(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function createDiagnosticsModule({ ui }) {
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
      if (val === null || val === undefined) return "\u2014";
      const seconds = val / 1000;
      return seconds < 10
        ? `${seconds.toFixed(1)}s`
        : `${Math.round(seconds)}s`;
    }

    function buildSummaryTable(summaryData) {
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Stage</th><th>p50</th><th>p95</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const [key, label] of Object.entries(STAGE_LABELS)) {
        const row = document.createElement("tr");
        const stage = summaryData[key] || {};
        row.innerHTML =
          "<td>" +
          label +
          "</td><td>" +
          formatMs(stage.p50) +
          "</td><td>" +
          formatMs(stage.p95) +
          "</td>";
        tbody.appendChild(row);
      }
      table.appendChild(tbody);
      return table;
    }

    function buildPluginsTable(items) {
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      const cols = ["Plugin", "Runs"].concat(Object.values(PLUGIN_AVG_LABELS));
      thead.innerHTML =
        "<tr>" +
        cols.map(function (c) {
          return "<th>" + c + "</th>";
        }).join("") +
        "</tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      items.slice(0, 10).forEach(function (item) {
        const row = document.createElement("tr");
        const cells = [item.plugin_id || "\u2014", String(item.runs || 0)];
        for (const key of Object.keys(PLUGIN_AVG_LABELS)) {
          cells.push(formatMs(item[key]));
        }
        row.innerHTML = cells
          .map(function (c) {
            return "<td>" + c + "</td>";
          })
          .join("");
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      return table;
    }

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
        panel.textContent = "";

        const summaryData = summary.summary || {};
        const hasData = Object.values(summaryData).some(function (stage) {
          return stage && stage.p50 !== null && stage.p50 !== undefined;
        });

        if (!hasData && (plugins.items || []).length === 0) {
          const emptyMsg = document.createElement("div");
          emptyMsg.className = "bench-empty";
          emptyMsg.textContent =
            "No benchmark data recorded in the last 24 hours. Benchmarks are collected automatically on each display refresh.";
          panel.appendChild(emptyMsg);
        } else {
          const heading1 = document.createElement("strong");
          heading1.textContent = "Benchmark Summary (24h)";
          panel.appendChild(heading1);
          panel.appendChild(buildSummaryTable(summaryData));

          if ((plugins.items || []).length > 0) {
            const heading2 = document.createElement("strong");
            heading2.textContent = "Per-plugin Averages";
            panel.appendChild(heading2);
            panel.appendChild(buildPluginsTable(plugins.items));
          }
        }
      } catch (e) {
        console.warn("Failed to load benchmark summary:", e);
        document.getElementById("benchSummary").textContent =
          "Failed to load benchmark summary";
      } finally {
        ui.setPanelLoading?.("benchSummary", false);
      }
    }

    function formatPercent(val) {
      if (val === null || val === undefined || Number.isNaN(Number(val))) {
        return "\u2014";
      }
      return `${Number(val).toFixed(1)}%`;
    }

    function formatDiskFree(val) {
      if (val === null || val === undefined || Number.isNaN(Number(val))) {
        return "\u2014";
      }
      return `${Number(val).toFixed(1)} GB free`;
    }

    function formatUptime(seconds) {
      if (
        seconds === null ||
        seconds === undefined ||
        Number.isNaN(Number(seconds))
      ) {
        return "\u2014";
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

    function buildSystemHealthTable(systemData) {
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Metric</th><th>Value</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const spec of SYSTEM_HEALTH_ROWS) {
        const row = document.createElement("tr");
        const labelCell = document.createElement("td");
        labelCell.textContent = spec.label;
        const valueCell = document.createElement("td");
        valueCell.textContent = spec.formatter(
          systemData ? systemData[spec.key] : null
        );
        row.appendChild(labelCell);
        row.appendChild(valueCell);
        tbody.appendChild(row);
      }
      table.appendChild(tbody);
      return table;
    }

    function buildPluginHealthTable(items) {
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Plugin</th><th>Status</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      const entries = Array.isArray(items)
        ? items.map(function (it) {
            return [it.plugin_id || "\u2014", it.status || it.state || "\u2014"];
          })
        : Object.entries(items || {}).map(function (pair) {
            const [pid, info] = pair;
            let status = "\u2014";
            if (info && typeof info === "object") {
              status = info.status || info.state || (info.ok === false ? "error" : "ok");
            } else if (typeof info === "string") {
              status = info;
            }
            return [pid, status];
          });
      if (entries.length === 0) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 2;
        cell.textContent = "No plugin health data";
        row.appendChild(cell);
        tbody.appendChild(row);
      } else {
        entries.forEach(function (pair) {
          const row = document.createElement("tr");
          const pidCell = document.createElement("td");
          pidCell.textContent = pair[0];
          const statusCell = document.createElement("td");
          statusCell.textContent = pair[1];
          row.appendChild(pidCell);
          row.appendChild(statusCell);
          tbody.appendChild(row);
        });
      }
      table.appendChild(tbody);
      return table;
    }

    function buildIsolationTable(isolationData) {
      const list = Array.isArray(isolationData?.isolated_plugins)
        ? isolationData.isolated_plugins
        : [];
      if (list.length === 0) {
        const msg = document.createElement("div");
        msg.className = "bench-empty";
        msg.textContent = "No plugins isolated";
        return msg;
      }
      const table = document.createElement("table");
      table.className = "bench-table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Plugin</th><th>Isolated</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      list.forEach(function (pluginId) {
        const row = document.createElement("tr");
        const pidCell = document.createElement("td");
        pidCell.textContent = pluginId;
        const statusCell = document.createElement("td");
        statusCell.textContent = "Yes";
        row.appendChild(pidCell);
        row.appendChild(statusCell);
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      return table;
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
        console.warn("Failed to load health data:", e);
        document.getElementById("healthSummary").textContent =
          "Failed to load health data";
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
        panel.textContent = "";
        panel.appendChild(buildIsolationTable(data || {}));
      } catch (e) {
        console.warn("Failed to load isolation list:", e);
        document.getElementById("isolationSummary").textContent =
          "Failed to load isolation list";
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
          const fallbackMsg = `Failed to ${verb} plugin`;
          const errMsg =
            typeof data?.error === "string"
              ? data.error
              : data?.error == null
                ? fallbackMsg
                : String(data.error);
          showResponseModal(
            "failure",
            errMsg.includes("registered")
              ? `Plugin "${pluginId}" is not a registered plugin. Check the ID and try again.`
              : errMsg
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

    let progressES = null;

    function initProgressSSE() {
      try {
        if (!globalThis.EventSource) return;
        progressES = new EventSource("/api/progress/stream");
        const refresh = () => refreshHealth();
        progressES.addEventListener("done", refresh);
        progressES.addEventListener("error", refresh);
      } catch (e) {
        console.warn("Progress SSE unavailable:", e);
      }
    }

    function teardown() {
      if (progressES) {
        progressES.close();
        progressES = null;
      }
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
      teardown,
      unIsolatePlugin,
    };
  }

  settingsModules.createDiagnosticsModule = createDiagnosticsModule;
})();

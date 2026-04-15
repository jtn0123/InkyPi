// In-app status badge (JTN-709).
//
// Polls /api/diagnostics (JTN-707) every 30s and surfaces a small floating
// badge in the page corner when something is wrong. Click opens a popover
// with the active issues and quick links (logs, pretty diagnostics, settings
// updates page).
//
// Badge state derivation:
//   ok      : refresh_task.last_error == null
//             AND every plugin_health value == "ok"
//             AND last_update_failure == null
//             AND recent_client_log_errors.count_5m == 0
//             AND recent_client_log_errors.warn_count_5m == 0
//   warning : any plugin_health == "unknown"
//             OR recent_client_log_errors.warn_count_5m > 0
//   error   : refresh_task.last_error != null
//             OR any plugin_health == "fail"
//             OR last_update_failure != null
//             OR recent_client_log_errors.count_5m > 0
//
// Error beats warning. The badge is hidden when state is "ok" so a healthy
// system shows no UI noise. If /api/diagnostics returns 401/403 the badge
// stays hidden permanently for this page load (the user isn't on the local
// network).
(function () {
  "use strict";

  // Opt-out: tests set this meta tag to avoid console noise and prevent the
  // fetch loop from racing with the test harness.
  const optOut = document.querySelector('meta[name="status-badge-disabled"]');
  if (optOut?.getAttribute("content") === "1") {
    return;
  }

  const ENDPOINT = "/api/diagnostics";
  const POLL_MS = 30_000;

  let badgeEl = null;
  let popoverEl = null;
  let pollTimer = null;
  let disabled = false;
  let currentState = "ok";

  function ensureBadge() {
    if (badgeEl) return badgeEl;
    badgeEl = document.getElementById("statusBadge");
    if (!badgeEl) {
      badgeEl = document.createElement("div");
      badgeEl.id = "statusBadge";
      badgeEl.className = "status-badge hidden";
      badgeEl.setAttribute("role", "status");
      badgeEl.setAttribute("aria-live", "polite");
      badgeEl.setAttribute("tabindex", "0");
      badgeEl.setAttribute("aria-label", "System status");
      badgeEl.hidden = true;
      const dot = document.createElement("span");
      dot.className = "status-badge-dot";
      dot.setAttribute("aria-hidden", "true");
      badgeEl.appendChild(dot);
      const label = document.createElement("span");
      label.className = "status-badge-label";
      label.textContent = "OK";
      badgeEl.appendChild(label);
      document.body.appendChild(badgeEl);
      badgeEl.addEventListener("click", togglePopover);
      badgeEl.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          togglePopover();
        } else if (ev.key === "Escape") {
          hidePopover();
        }
      });
    }
    return badgeEl;
  }

  function setState(state, issues, raw) {
    currentState = state;
    const el = ensureBadge();
    el.classList.remove("status-ok", "status-warning", "status-error");
    el.classList.add(`status-${state}`);
    const label = el.querySelector(".status-badge-label");
    if (state === "ok") {
      if (label) label.textContent = "OK";
      el.classList.add("hidden");
      el.hidden = true;
      el.setAttribute("aria-label", "System status: OK");
      hidePopover();
    } else {
      if (label)
        label.textContent = state === "error" ? "Issue" : "Check status";
      el.classList.remove("hidden");
      el.hidden = false;
      el.setAttribute(
        "aria-label",
        `System status: ${state === "error" ? "error" : "warning"} — ${issues.length} issue${issues.length === 1 ? "" : "s"}`
      );
    }
    el.dataset.state = state;
    el.dataset.issueCount = String(issues.length);
    el.__issues = issues;
    el.__rawDiagnostics = raw;
    if (popoverEl && !popoverEl.hidden) {
      renderPopover();
    }
  }

  function deriveState(data) {
    const issues = [];
    const rt = data?.refresh_task || {};
    if (rt.last_error) {
      issues.push({
        severity: "error",
        label: "Refresh task error",
        detail: String(rt.last_error).slice(0, 200),
      });
    }
    const ph = data?.plugin_health || {};
    const failed = [];
    const unknown = [];
    for (const [pid, status] of Object.entries(ph)) {
      if (status === "fail") failed.push(pid);
      else if (status === "unknown") unknown.push(pid);
    }
    if (failed.length) {
      issues.push({
        severity: "error",
        label: "Plugin failure",
        detail: failed.join(", "),
      });
    }
    if (data?.last_update_failure) {
      issues.push({
        severity: "error",
        label: "Update failed",
        detail: "Last update did not complete",
        link: "/settings#updates",
      });
    }
    const rc = data?.recent_client_log_errors || {};
    if ((rc.count_5m || 0) > 0) {
      issues.push({
        severity: "error",
        label: "Browser errors",
        detail: `${rc.count_5m} error${rc.count_5m === 1 ? "" : "s"} in the last 5 minutes`,
      });
    } else if ((rc.warn_count_5m || 0) > 0) {
      issues.push({
        severity: "warning",
        label: "Browser warnings",
        detail: `${rc.warn_count_5m} warning${rc.warn_count_5m === 1 ? "" : "s"} in the last 5 minutes`,
      });
    }
    if (unknown.length && failed.length === 0) {
      issues.push({
        severity: "warning",
        label: "Plugin health unknown",
        detail: unknown.slice(0, 5).join(", "),
      });
    }

    let state = "ok";
    if (issues.some((i) => i.severity === "error")) {
      state = "error";
    } else if (issues.some((i) => i.severity === "warning")) {
      state = "warning";
    }
    return { state, issues };
  }

  function renderPopover() {
    if (!popoverEl) return;
    const issues = badgeEl?.__issues || [];
    popoverEl.innerHTML = "";

    const heading = document.createElement("div");
    heading.className = "status-popover-heading";
    heading.textContent =
      currentState === "error" ? "Something needs attention" : "Check status";
    popoverEl.appendChild(heading);

    const list = document.createElement("ul");
    list.className = "status-popover-list";
    for (const issue of issues) {
      const li = document.createElement("li");
      li.className = `status-popover-item severity-${issue.severity}`;
      const strong = document.createElement("strong");
      strong.textContent = issue.label;
      li.appendChild(strong);
      if (issue.detail) {
        const detail = document.createElement("span");
        detail.className = "status-popover-detail";
        detail.textContent = ": " + issue.detail;
        li.appendChild(detail);
      }
      if (issue.link) {
        const a = document.createElement("a");
        a.href = issue.link;
        a.className = "status-popover-link";
        a.textContent = "Open";
        li.appendChild(document.createTextNode(" "));
        li.appendChild(a);
      }
      list.appendChild(li);
    }
    popoverEl.appendChild(list);

    const actions = document.createElement("div");
    actions.className = "status-popover-actions";
    const logsLink = document.createElement("a");
    logsLink.href = "/download-logs";
    logsLink.className = "status-popover-action";
    logsLink.textContent = "Download logs";
    actions.appendChild(logsLink);
    const diagLink = document.createElement("a");
    diagLink.href = ENDPOINT;
    diagLink.className = "status-popover-action";
    diagLink.target = "_blank";
    diagLink.rel = "noopener";
    diagLink.textContent = "Raw diagnostics";
    actions.appendChild(diagLink);
    popoverEl.appendChild(actions);
  }

  function ensurePopover() {
    if (popoverEl) return popoverEl;
    popoverEl = document.createElement("div");
    popoverEl.id = "statusBadgePopover";
    popoverEl.className = "status-popover";
    popoverEl.setAttribute("role", "dialog");
    popoverEl.setAttribute("aria-label", "Active issues");
    popoverEl.hidden = true;
    document.body.appendChild(popoverEl);
    document.addEventListener("click", (ev) => {
      if (popoverEl.hidden) return;
      if (ev.target === badgeEl || badgeEl?.contains(ev.target)) return;
      if (popoverEl.contains(ev.target)) return;
      hidePopover();
    });
    return popoverEl;
  }

  function togglePopover() {
    const el = ensurePopover();
    if (el.hidden) {
      renderPopover();
      el.hidden = false;
      el.classList.add("visible");
    } else {
      hidePopover();
    }
  }

  function hidePopover() {
    if (!popoverEl) return;
    popoverEl.hidden = true;
    popoverEl.classList.remove("visible");
  }

  async function poll() {
    if (disabled) return;
    try {
      const resp = await fetch(ENDPOINT, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (resp.status === 401 || resp.status === 403) {
        // Gracefully hide — the viewer isn't on the local network.
        disabled = true;
        if (badgeEl) {
          badgeEl.classList.add("hidden");
          badgeEl.hidden = true;
        }
        stopPolling();
        return;
      }
      if (!resp.ok) return;
      const data = await resp.json();
      const { state, issues } = deriveState(data);
      setState(state, issues, data);
    } catch (_err) {
      // Network blip — swallow; the next tick will retry.
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = window.setInterval(poll, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function handleVisibility() {
    if (document.visibilityState === "visible" && !disabled) {
      poll();
    }
  }

  function init() {
    ensureBadge();
    poll();
    startPolling();
    document.addEventListener("visibilitychange", handleVisibility);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Expose a minimal test hook so integration tests can force a refresh
  // without waiting on the 30s poll timer.
  window.__statusBadge = {
    refresh: poll,
    getState: () => currentState,
  };
})();

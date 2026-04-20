(function () {
  const settingsModules =
    globalThis.InkyPiSettingsModules ||
    (globalThis.InkyPiSettingsModules = {});

  function showCopyFeedback(btn, success) {
    if (!btn) return;
    const original = btn.textContent;
    btn.textContent = success ? "Copied!" : "Copy failed";
    setTimeout(() => {
      btn.textContent = original;
    }, 1500);
  }

  async function copyText(text) {
    if (!navigator.clipboard || !globalThis.isSecureContext) {
      return false;
    }
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      console.warn("Clipboard write failed:", e);
      return false;
    }
  }

  function getFormSnapshot(form) {
    const target = form || document.querySelector(".settings-form");
    if (!target) return {};
    const snap = {};
    for (const el of target.querySelectorAll("input, select, textarea")) {
      const key = el.name || el.id;
      if (!key) continue;
      snap[key] = el.type === "checkbox" ? el.checked : el.value;
    }
    return snap;
  }

  function restoreFormFromSnapshot(form, snapshot) {
    if (!form || !snapshot) return;
    for (const el of form.querySelectorAll("input, select, textarea")) {
      const key = el.name || el.id;
      if (!key || !(key in snapshot)) continue;
      if (el.type === "checkbox") {
        el.checked = snapshot[key];
      } else {
        el.value = snapshot[key];
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  function isErrorLine(line) {
    return /\b(ERROR|CRITICAL|Exception|Traceback)\b/i.test(line);
  }

  function isWarnLine(line) {
    return /\bWARNING\b/i.test(line);
  }

  function setTextIfPresent(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function renderUpdateFailureUnreadable(banner) {
    setTextIfPresent("updateFailureTimestamp", "");
    setTextIfPresent("updateFailureExitCode", "");
    setTextIfPresent(
      "updateFailureStep",
      "Last update failure record was unreadable."
    );
    const details = document.getElementById("updateFailureDetails");
    if (details) details.hidden = true;
    banner.hidden = false;
  }

  function renderUpdateFailureFields(lastFailure) {
    const tsText = lastFailure.timestamp
      ? `Failed at ${lastFailure.timestamp}`
      : "";
    const codeText =
      typeof lastFailure.exit_code === "number"
        ? `exit ${lastFailure.exit_code}`
        : "";
    const stepText = lastFailure.last_command
      ? `step: ${lastFailure.last_command}`
      : "";
    setTextIfPresent("updateFailureTimestamp", tsText);
    setTextIfPresent("updateFailureExitCode", codeText);
    setTextIfPresent("updateFailureStep", stepText);

    const journalText = lastFailure.recent_journal_lines || "";
    setTextIfPresent("updateFailureJournal", journalText);
    const details = document.getElementById("updateFailureDetails");
    if (details) details.hidden = !journalText;
  }

  function renderRollbackButton(lastFailure, prevVersion) {
    const btn = document.getElementById("rollbackUpdateBtn");
    if (!btn) return;
    const canRollback =
      !!lastFailure &&
      typeof prevVersion === "string" &&
      prevVersion.length > 0;
    btn.hidden = !canRollback;
    if (canRollback) {
      const target = document.getElementById("rollbackTargetVersion");
      if (target) target.textContent = prevVersion;
      btn.dataset.prevVersion = prevVersion;
    } else {
      delete btn.dataset.prevVersion;
    }
  }

  function renderUpdateFailureBanner(lastFailure, prevVersion) {
    const banner = document.getElementById("updateFailureBanner");
    if (!banner) return;
    if (!lastFailure) {
      banner.hidden = true;
      renderRollbackButton(null, null);
      return;
    }
    if (lastFailure.parse_error) {
      renderUpdateFailureUnreadable(banner);
      renderRollbackButton(lastFailure, prevVersion);
      return;
    }
    renderUpdateFailureFields(lastFailure);
    banner.hidden = false;
    renderRollbackButton(lastFailure, prevVersion);
  }

  function prefKey(key) {
    return `logs_${key}`;
  }

  settingsModules.shared = {
    copyText,
    getFormSnapshot,
    isErrorLine,
    isWarnLine,
    prefKey,
    renderUpdateFailureBanner,
    restoreFormFromSnapshot,
    showCopyFeedback,
  };
})();

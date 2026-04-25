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
    // Prefer the async Clipboard API when the page is a secure context
    // (HTTPS, localhost). InkyPi is commonly served on the LAN over plain
    // HTTP, which browsers treat as insecure and therefore block the async
    // API. We fall through to a legacy execCommand-based path below so the
    // Copy buttons still work in that setup.
    if (navigator.clipboard && globalThis.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (e) {
        console.warn("Clipboard write failed, trying fallback:", e);
      }
    }
    return copyTextViaExecCommand(text);
  }

  function copyTextViaExecCommand(text) {
    if (typeof document === "undefined" || !document.body) return false;
    const ta = document.createElement("textarea");
    ta.value = text;
    // Keep the textarea off-screen but selectable. iOS requires a non-zero
    // font-size or it silently refuses to select; the rest of these styles
    // stop the page from scrolling when we focus it.
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "0";
    ta.style.width = "1px";
    ta.style.height = "1px";
    ta.style.padding = "0";
    ta.style.border = "0";
    ta.style.opacity = "0";
    ta.style.pointerEvents = "none";
    document.body.appendChild(ta);
    const prevActive = document.activeElement;
    try {
      ta.focus({ preventScroll: true });
      ta.select();
      ta.setSelectionRange(0, text.length);
      return document.execCommand("copy");
    } catch (e) {
      console.warn("execCommand copy failed:", e);
      return false;
    } finally {
      ta.remove();
      if (prevActive && typeof prevActive.focus === "function") {
        try {
          prevActive.focus({ preventScroll: true });
        } catch (_) {
          /* ignore */
        }
      }
    }
  }

  function getFormSnapshot(form) {
    const target = form || document.querySelector(".settings-form");
    if (!target) return {};
    const snap = {};
    for (const el of target.querySelectorAll("input, select, textarea")) {
      const key = el.name || el.id;
      if (!key) continue;
      if (el.type === "checkbox") {
        snap[key] = el.checked;
      } else if (el.type === "radio") {
        // Radio groups share a name — only capture the value of the
        // currently-checked radio so the dirty check can tell when the
        // user toggles between options (e.g. orientation: horizontal ↔
        // vertical). Without this guard the last radio in DOM order
        // always wins and toggling never looks dirty.
        if (el.checked) {
          snap[key] = el.value;
        } else if (!(key in snap)) {
          snap[key] = null;
        }
      } else {
        snap[key] = el.value;
      }
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
      } else if (el.type === "radio") {
        el.checked = snapshot[key] === el.value;
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

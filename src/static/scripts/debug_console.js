/**
 * Debug console — floating panel that captures frontend JS errors.
 *
 * The button is rendered bottom-left and is only visible after the first error
 * is recorded (or immediately if errors were already caught before the DOM was
 * ready). It is deliberately separate from the server-side "Error Logs" page
 * (/errors) so the two features are never confused.
 *
 * Label used throughout: "Debug console" (button title, panel heading,
 * aria-label). The server-side feature keeps its own "Error Logs" label.
 *
 * Callback-only entries (matching the pattern /^[a-zA-Z]+\.on[A-Z]\w+$/)
 * are filtered out — they are raw event-handler names that provide no
 * actionable information to a user.
 *
 * JTN-587
 */
(function () {
  "use strict";

  /** Maximum number of entries kept in memory. */
  var MAX_ENTRIES = 50;

  /**
   * Raw callback names like `useWebSocket.onerror` are not useful to users.
   * Filter them out before displaying.
   * @param {string} msg
   * @returns {boolean} true if the message should be kept
   */
  function isUsefulMessage(msg) {
    // Drop bare callback-name patterns: identifier.onSomething
    return !/^[a-zA-Z_$][\w$.]*\.on[A-Z]\w*$/.test(msg.trim());
  }

  var _entries = [];
  var _button = null;
  var _panel = null;
  var _list = null;

  function _addEntry(msg) {
    if (!isUsefulMessage(msg)) return;
    _entries.push({ ts: new Date().toISOString(), msg: msg });
    if (_entries.length > MAX_ENTRIES) {
      _entries.shift();
    }
    _syncBadge();
    _renderList();
  }

  function _syncBadge() {
    if (!_button) return;
    var count = _entries.length;
    _button.hidden = count === 0;
    var badge = _button.querySelector(".debug-console-badge");
    if (badge) {
      badge.textContent = count > 99 ? "99+" : String(count);
    }
  }

  function _renderList() {
    if (!_list) return;
    _list.innerHTML = "";
    if (_entries.length === 0) {
      var empty = document.createElement("li");
      empty.className = "debug-console-empty";
      empty.textContent = "No errors recorded.";
      _list.appendChild(empty);
      return;
    }
    _entries.forEach(function (entry) {
      var li = document.createElement("li");
      li.className = "debug-console-entry";
      var time = document.createElement("time");
      time.className = "debug-console-time";
      time.textContent = entry.ts.slice(11, 19); // HH:MM:SS
      var msg = document.createElement("span");
      msg.className = "debug-console-msg";
      msg.textContent = entry.msg;
      li.appendChild(time);
      li.appendChild(msg);
      _list.appendChild(li);
    });
  }

  function _buildUI() {
    // --- Floating toggle button ---
    _button = document.createElement("button");
    _button.type = "button";
    _button.id = "debugConsoleToggle";
    _button.className = "debug-console-toggle";
    _button.title = "Debug console";
    _button.setAttribute("aria-label", "Open debug console");
    _button.setAttribute("aria-expanded", "false");
    _button.setAttribute("aria-controls", "debugConsolePanel");
    // Hide until we have at least one error
    _button.hidden = true;

    // Bug icon (inline SVG — no external dependency)
    _button.innerHTML =
      '<svg class="debug-console-icon" viewBox="0 0 24 24" width="18" height="18" ' +
      'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M9 9a3 3 0 0 1 6 0"/>' +
      '<path d="M12 12v3"/>' +
      '<path d="M7.5 12H4a8 8 0 0 0 16 0h-3.5"/>' +
      '<path d="M6.5 7.5 4 6"/>' +
      '<path d="M17.5 7.5 20 6"/>' +
      "<path d=\"M8 19.5C8 21 10 22 12 22s4-1 4-2.5\"/>" +
      "</svg>" +
      '<span class="debug-console-badge" aria-hidden="true">0</span>';

    // --- Panel ---
    _panel = document.createElement("div");
    _panel.id = "debugConsolePanel";
    _panel.className = "debug-console-panel";
    _panel.setAttribute("role", "dialog");
    _panel.setAttribute("aria-modal", "false");
    _panel.setAttribute("aria-label", "Debug console");
    _panel.hidden = true;

    var header = document.createElement("div");
    header.className = "debug-console-header";

    var heading = document.createElement("h2");
    heading.className = "debug-console-title";
    heading.textContent = "Debug console";

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "debug-console-close";
    closeBtn.setAttribute("aria-label", "Close debug console");
    closeBtn.textContent = "\u00d7"; // ×

    header.appendChild(heading);
    header.appendChild(closeBtn);

    _list = document.createElement("ul");
    _list.className = "debug-console-list";
    _list.setAttribute("aria-label", "Recorded frontend errors");
    _renderList();

    _panel.appendChild(header);
    _panel.appendChild(_list);

    // --- Wire events ---
    _button.addEventListener("click", function () {
      var open = _panel.hidden;
      _panel.hidden = !open;
      _button.setAttribute("aria-expanded", String(open));
      if (open) {
        closeBtn.focus();
      }
    });

    closeBtn.addEventListener("click", function () {
      _panel.hidden = true;
      _button.setAttribute("aria-expanded", "false");
      _button.focus();
    });

    document.body.appendChild(_button);
    document.body.appendChild(_panel);
  }

  // Intercept errors that fire before DOMContentLoaded
  var _earlyErrors = [];
  var _origOnerror = window.onerror;

  window.onerror = function (msg, src, line, col, err) {
    var text = err && err.message ? err.message : (typeof msg === "string" ? msg : "Uncaught error");
    _earlyErrors.push(text);
    if (_origOnerror) return _origOnerror.apply(this, arguments);
  };

  var _origOnUnhandled = window.onunhandledrejection;
  window.addEventListener("unhandledrejection", function (evt) {
    var reason = evt.reason;
    var text =
      reason instanceof Error
        ? reason.message || "Unhandled promise rejection"
        : typeof reason === "string"
        ? reason
        : "Unhandled promise rejection";
    _earlyErrors.push(text);
  });

  document.addEventListener("DOMContentLoaded", function () {
    _buildUI();
    // Flush errors captured before DOM was ready
    _earlyErrors.forEach(function (msg) {
      _addEntry(msg);
    });
    _earlyErrors = [];

    // Forward future errors
    window.addEventListener("error", function (evt) {
      var text =
        evt.error && evt.error.message
          ? evt.error.message
          : evt.message || "Uncaught error";
      _addEntry(text);
    });

    window.addEventListener("unhandledrejection", function (evt) {
      var reason = evt.reason;
      var text =
        reason instanceof Error
          ? reason.message || "Unhandled promise rejection"
          : typeof reason === "string"
          ? reason
          : "Unhandled promise rejection";
      _addEntry(text);
    });
  });

  // Expose for testing only
  window.__debugConsole = {
    addEntry: _addEntry,
    getEntries: function () { return _entries.slice(); },
    isUsefulMessage: isUsefulMessage,
  };
})();

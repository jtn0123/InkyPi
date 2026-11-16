const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const scenario = process.argv[2];
const root = process.argv[3];
const unhandled = [];
process.on("unhandledRejection", reason => unhandled.push(reason));
const feedback = [];
const scheduled = [];
const flush = () => new Promise(resolve => setImmediate(resolve));
const listeners = {};
const emptyNode = () => ({hidden: true, innerHTML: "", classList: {toggle() {}}});
const nodes = scenario === "dashboard" ? {
  imageMeta: emptyNode(), imageMetaContent: emptyNode(),
  dashboardRefreshBtn: {addEventListener: (name, callback) => {listeners[name] = callback;}},
} : {};
const sandbox = {
  console: {warn() {}, debug() {}, error() {}}, Date, Intl, Promise, Headers, URL,
  document: {getElementById: id => nodes[id] || null, querySelectorAll: () => [], querySelector: () => null},
  setTimeout(callback, delay) {scheduled.push({callback, delay}); return scheduled.length;},
  setInterval() {return 1;}, clearInterval() {}, addEventListener() {},
  EventSource: class extends EventTarget {close() {}},
  showResponseModal(status, message) {feedback.push({status, message});},
  fetch: async url => ({ok: true, status: 200, redirected: false, url, text: async () => {
    if (scenario === "dashboard" && url === "/refresh") {
      return JSON.stringify({plugin_id: "weather", plugin_meta: {date: "invalid-external-date"}});
    }
    if (url === "/display") return JSON.stringify({success: true, message: "Displayed"});
    return JSON.stringify({plugin_id: "countdown", refresh_time: "2026-10-01T12:00:00Z"});
  }}),
};
sandbox.globalThis = sandbox;
sandbox.window = sandbox;
const context = vm.createContext(sandbox);
// Page scripts read JSON through the shared fetchJson helper, which the
// common bundle loads first.
const load = script => {
  const file = path.join(root, "src/static/scripts", script);
  vm.runInContext(fs.readFileSync(file, "utf8"), context, {filename: file});
};
load("fetch_json.js");

async function main() {
  if (scenario === "dashboard") {
    load("dashboard_page.js");
    sandbox.InkyPiDashboardPage.create({resolution: [800, 480], pushUrl: "/events", refreshInfoUrl: "/refresh", nextUpUrl: "/next"}).init();
    // Startup hydration owns its own failure; isolate the manual action boundary.
    await flush();
    await flush();
    feedback.length = 0;
    listeners.click();
    await flush();
    await flush();
    assert.equal(feedback.filter(item => item.status === "failure").length, 1,
      "Invalid external metadata must surface a refresh failure");
  } else {
    sandbox.InkyPiPluginPageShared = {
      setHidden() {}, validateAddToPlaylistAction: () => true,
      formatPreviewTimestamp: value => (value ? String(value) : "\u2014"),
      setCurrentDisplayRefresh() {throw new Error("preview renderer unavailable");},
    };
    sandbox.InkyPiPluginPageProgress = {createProgressController: () => ({saveLastProgressSnapshot() {}})};
    sandbox.PluginForm = {sendForm: async options => {options.onAfterSuccess();}};
    load("plugin_page.js");
    sandbox.InkyPiPluginPage.create({pluginId: "countdown", refreshInfoUrl: "/refresh", displayInstanceUrl: "/display"});
    if (scenario === "plugin-instance") await sandbox.displayInstanceNow();
    else await sandbox.handleAction("update_now", {disabled: false});
    const task = scheduled.find(item => item.delay === (scenario === "plugin-instance" ? 400 : 250));
    assert.ok(task, "Successful update schedules preview reconciliation");
    task.callback();
    await flush();
    await flush();
    const failures = feedback.filter(item => item.status === "failure");
    assert.equal(failures.length, 1, "Detached preview failure must have a rejection sink and feedback");
    assert.match(failures[0].message, /preview/i);
    assert.doesNotMatch(failures[0].message, /Failed to display|Failed to update/i,
      "Successful display operation must not be misreported as failed");
    if (scenario === "plugin-instance") assert.equal(feedback.filter(item => item.status === "success").length, 1);
  }
  assert.equal(unhandled.length, 0, "No event-boundary promise rejection may escape");
}
main().catch(error => {console.error(error); process.exitCode = 1;});

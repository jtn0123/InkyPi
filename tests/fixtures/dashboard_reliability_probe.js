// Execute the shipped controller with native EventTarget delivery and controlled HTTP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const scenario = process.argv[2];
const source = process.argv[3];
const calls = [];
const intervals = new Map();
const lifecycle = {};
const delayedUrls = new Set();
const delayedResponses = [];
let storeState;
const unhandled = [];
process.on('unhandledRejection', error => unhandled.push(error));
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
const nodes = Object.fromEntries([
  'heroNowValue', 'heroNowMeta', 'heroNextValue', 'heroNextMeta',
  'heroRefreshValue', 'heroRefreshMeta', 'connectivityWarning', 'overviewEmpty',
  'dashboardRefreshBtn', 'kpiRefreshes', 'kpiAvgRender', 'kpiErrors',
  'kpiStorageFree', 'todayKpiSub', 'previewImage',
].map(id => [id, {
  textContent: '', hidden: true, title: '', handlers: {}, dataset: {}, style: {},
  classList: {toggle() {}, remove() {}, add() {}},
  addEventListener(name, callback) { this.handlers[name] = callback; },
  setAttribute() {},
}]));
const quickSwitchRows = [1, 2].map(version => ({
  dataset: {playlistName: `Morning ${version}`}, active: false,
  classList: {toggle(_name, active) { quickSwitchRows[version - 1].active = active; }},
  querySelector() { return null; },
}));
class Source extends EventTarget {
  constructor(url) { super(); this.url = url; this.closed = false; Source.instance = this; }
  set onmessage(callback) { this.addEventListener('message', callback); }
  set onopen(callback) { this.addEventListener('open', callback); }
  set onerror(callback) { this.addEventListener('error', callback); }
  close() { this.closed = true; }
}
let generation = 1;
const failures = new Set();
let failureKind = 'http';
const sandbox = {
  console: {warn() {}}, Date, Intl, Promise, EventSource: Source,
  InkyPiStore: {createStore(initial) {
    storeState = {...initial};
    return {get: key => storeState[key], set: values => Object.assign(storeState, values)};
  }},
  document: {
    getElementById: id => nodes[id] || null,
    querySelectorAll: selector => selector === '[data-quick-switch-row]' ? quickSwitchRows : [],
  },
  addEventListener(name, callback) { (lifecycle[name] ||= []).push(callback); },
  setInterval(callback, ms) { const id = intervals.size + 1; intervals.set(id, {callback, ms}); return id; },
  clearInterval(id) { intervals.delete(id); },
  setTimeout() {}, showResponseModal() {},
  fetch: async url => {
    calls.push(url);
    const version = generation;
    const failed = failures.has(url);
    if (version === 1 && delayedUrls.has(url)) {
      await new Promise(resolve => delayedResponses.push(resolve));
    }
    if (failed && failureKind === 'network') throw new Error('offline');
    return {
      ok: !failed, status: failed ? 503 : 200,
      json: async () => {
        if (failed) return {success: false, error: 'unavailable'};
        if (url === '/refresh') return {
          plugin_id: version === 3 ? null : 'weather',
          plugin_display_name: `Weather ${version}`, playlist: `Morning ${version}`,
          refresh_time: '2026-10-01T12:00:00Z', cycle_minutes: 15,
          next_refresh_meta: `Generation ${version} cadence`, image_hash: `hash-${version}`,
        };
        if (url === '/next') return {plugin_id: version === 3 ? null : 'countdown', plugin_display_name: `Countdown ${version}`, playlist: `Next ${version}`};
        if (url === '/stats') return {last_24h: {total: version, failure: 0, p50_duration_ms: 1000}};
        return {disk_free_gb: version};
      },
    };
  },
};
sandbox.globalThis = sandbox;
vm.runInNewContext(fs.readFileSync(source, 'utf8'), sandbox, {filename: source});
const count = url => calls.filter(call => call === url).length;
const refresh = async () => { nodes.dashboardRefreshBtn.handlers.click(); await flush(); };
const dispatch = async name => { Source.instance.dispatchEvent(new Event(name)); await flush(); };

async function main() {
  const noPush = scenario === 'polling';
  if (scenario === 'race-preview' || scenario === 'race-warning') {
    delayedUrls.add('/refresh');
    delayedUrls.add('/next');
  }
  if (scenario === 'race-kpis' || scenario === 'race-kpi-warning') {
    delayedUrls.add('/stats');
    delayedUrls.add('/health');
  }
  if (scenario === 'race-warning') {
    failures.add('/refresh');
    failures.add('/next');
  }
  if (scenario === 'race-kpi-warning') {
    failures.add('/stats');
    failures.add('/health');
  }
  sandbox.InkyPiDashboardPage.create({
    resolution: [800, 480], pushUrl: noPush ? null : '/events',
    refreshInfoUrl: '/refresh', nextUpUrl: '/next', statsUrl: '/stats', systemHealthUrl: '/health',
  }).init();
  await flush();
  if (scenario.startsWith('race-')) {
    generation = 2;
    failures.clear();
    await dispatch('refresh_complete');
    assert.equal(nodes.heroNowValue.textContent, 'Weather 2');
    assert.equal(nodes.connectivityWarning.hidden, true);
    for (const resolve of delayedResponses) resolve();
    await flush();
    assert.equal(nodes.heroNowValue.textContent, 'Weather 2', 'Earlier responses must not overwrite newer current data');
    assert.equal(nodes.heroNextValue.textContent, 'Countdown 2', 'Earlier responses must not overwrite newer next data');
    assert.match(nodes.heroNowMeta.textContent, /Morning 2/);
    assert.equal(nodes.heroNextMeta.textContent, 'Playlist: Next 2');
    assert.equal(nodes.heroRefreshMeta.textContent, 'Generation 2 cadence');
    assert.equal(storeState.imageHash, 'hash-2');
    assert.deepEqual(quickSwitchRows.map(row => row.active), [false, true]);
    assert.equal(nodes.connectivityWarning.hidden, true, 'An older failure must not undo current recovery');
    assert.equal(nodes.kpiRefreshes.textContent, '2', 'Earlier stats must not overwrite newer telemetry');
    assert.equal(nodes.kpiStorageFree.textContent, '2.0 GB');
    assert.equal(nodes.todayKpiSub.textContent, 'Last 24h snapshot', 'Earlier telemetry failures must not undo recovery');
  } else if (scenario.startsWith('kpi-')) {
    if (scenario !== 'kpi-partial-health') failures.add('/stats');
    if (scenario !== 'kpi-partial') failures.add('/health');
    await refresh();
    assert.equal(nodes.kpiRefreshes.textContent, '1', 'Failed telemetry retains its last good value');
    assert.equal(nodes.kpiStorageFree.textContent, '1.0 GB');
    assert.equal(nodes.todayKpiSub.textContent, scenario === 'kpi-unavailable' ? 'Telemetry unavailable' : 'Some telemetry unavailable');
    failures.clear();
    generation = 2;
    await refresh();
    assert.equal(nodes.kpiRefreshes.textContent, '2');
    assert.equal(nodes.todayKpiSub.textContent, 'Last 24h snapshot');
  } else if (scenario === 'initial') {
    assert.equal(count('/refresh'), 1, 'SSE startup must hydrate current status');
    assert.equal(count('/next'), 1, 'SSE startup must hydrate next item');
  } else if (scenario.startsWith('event:')) {
    const before = count('/refresh');
    const beforeStats = count('/stats');
    generation = 2;
    await dispatch(scenario.slice(6));
    assert.equal(count('/refresh'), before + 1, 'Named/default event must refresh metadata');
    assert.equal(count('/next'), before + 1, 'Named/default event must refresh next item');
    assert.equal(nodes.heroNowValue.textContent, 'Weather 2');
    assert.equal(count('/stats'), beforeStats + 1, 'Refresh lifecycle events must refresh KPIs');
    assert.equal(nodes.kpiRefreshes.textContent, '2');
  } else if (scenario === 'reconnect') {
    await dispatch('open');
    const before = count('/refresh');
    generation = 2;
    await dispatch('open');
    assert.equal(count('/refresh'), before + 1, 'Each successful open must reconcile missed events');
    assert.equal(nodes.heroNowValue.textContent, 'Weather 2');
  } else if (scenario === 'polling' || scenario === 'fallback') {
    if (!noPush) {
      await dispatch('error');
      await dispatch('error');
      assert.equal(Source.instance.closed, true);
    }
    const polling = [...intervals.values()].filter(timer => timer.ms === 5000);
    assert.equal(polling.length, 1, 'Fallback owns exactly one polling timer');
    generation = 2;
    polling[0].callback();
    await flush();
    assert.equal(nodes.heroNowValue.textContent, 'Weather 2');
    for (const callback of lifecycle.pagehide) callback();
    assert.equal(intervals.size, 0, 'Page exit must release polling and countdown timers');
  } else {
    await refresh(); // Establish known-good values independent of the C4 startup defect.
    assert.equal(nodes.heroNowValue.textContent, 'Weather 1');
    assert.equal(nodes.heroNextValue.textContent, 'Countdown 1');
    generation = 2;
    if (scenario === 'partial-current') failures.add('/refresh');
    else if (scenario === 'partial-next') failures.add('/next');
    else { failures.add('/refresh'); failures.add('/next'); }
    if (scenario === 'network') failureKind = 'network';
    for (let index = 0; index < 3; index++) await refresh();
    assert.equal(nodes.heroNowValue.textContent, scenario === 'partial-next' ? 'Weather 2' : 'Weather 1', 'Failed current endpoint must retain last good value');
    assert.equal(nodes.heroNextValue.textContent, scenario === 'partial-current' ? 'Countdown 2' : 'Countdown 1', 'Failed next endpoint must retain last good value');
    assert.equal(nodes.connectivityWarning.hidden, false, 'Partial/full repeated failures must remain visible');
    if (scenario === 'recovery' || scenario === 'empty-success') {
      failures.clear();
      if (scenario === 'empty-success') generation = 3;
      await refresh();
      assert.equal(nodes.connectivityWarning.hidden, true, 'Full successful recovery clears warning');
      assert.equal(nodes.heroNowValue.textContent, scenario === 'empty-success' ? 'Idle' : 'Weather 2');
      assert.equal(nodes.heroNextValue.textContent, scenario === 'empty-success' ? '\u2014' : 'Countdown 2');
    }
  }
  await flush();
  assert.equal(unhandled.length, 0, 'No detached refresh promise may reject unhandled');
}
main().catch(error => {console.error(error); process.exitCode = 1;});

// Plugin Form Module
// Extracted from plugin.html to keep templates declarative.
(function(){
  'use strict';

  // The whole request, including a background render, gives up after this.
  const REQUEST_TIMEOUT_MS = 90000;
  // How often to ask /api/job/<id> about a background render. Without the
  // live progress stream, polling also moves the progress bar, so it runs
  // every second. While the stream is reporting steps, polling only has to
  // collect the result. Once the stream says the render ended, the job
  // record follows within moments, so check again almost at once.
  const POLL_MS = 1000;
  const POLL_MS_WHILE_LIVE = 3000;
  const POLL_MS_AFTER_LIVE_END = 250;
  const TIMEOUT_MESSAGE =
    'Request timed out. The plugin may still be processing — check back in a moment.';
  const METRIC_LABELS = [
    ['Request', 'request_ms'],
    ['Generate', 'generate_ms'],
    ['Preprocess', 'preprocess_ms'],
    ['Display', 'display_ms']
  ];

  function $(id){ return document.getElementById(id); }

  function notify(kind, message){
    if (window.showResponseModal) window.showResponseModal(kind, message);
  }

  function initProgress(){
    let t0 = 0;
    let clockTimer = null;
    let lastStepBase = '';

    const els = {
      block: $('requestProgress'),
      text: $('requestProgressText'),
      bar: $('requestProgressBar'),
      // Native <progress> twin of the visual bar — updated alongside it so
      // screen-reader users get standard progressbar semantics without the
      // custom role="progressbar" (SonarCloud Web:S6819).
      meter: $('requestProgressBarMeter'),
      list: $('requestProgressList'),
      clock: $('requestProgressClock'),
      elapsed: $('requestProgressElapsed')
    };

    function fmtElapsed(ms){
      const s = Math.floor(ms / 1000);
      const m = Math.floor(s / 60);
      return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
    }

    function tickClock(){
      try {
        if (els.clock) els.clock.textContent = new Date().toLocaleTimeString();
        const elapsedMs = Date.now() - t0;
        if (els.elapsed) els.elapsed.textContent = fmtElapsed(elapsedMs);
        // A step that has run for a while shows how long, so the page
        // doesn't look stuck.
        const finished = lastStepBase.includes('Done') || lastStepBase.includes('Failed');
        if (elapsedMs > 15000 && lastStepBase && els.text && !finished) {
          els.text.textContent = lastStepBase + ' (' + fmtElapsed(elapsedMs) + ')';
        }
      } catch {}
    }

    function setStep(text, pct){
      lastStepBase = text;
      if (els.block) {
        els.block.hidden = false;
        els.block.style.display = '';
      }
      if (els.text) els.text.textContent = text;
      if (els.bar && typeof pct === 'number') {
        els.bar.style.width = pct + '%';
        if (els.meter) els.meter.value = pct;
      }
      if (els.list) {
        const li = document.createElement('li');
        const ts = document.createElement('time');
        ts.dateTime = new Date().toISOString();
        ts.textContent = new Date().toLocaleTimeString();
        li.appendChild(ts);
        li.appendChild(document.createTextNode(' ' + text));
        els.list.appendChild(li);
        try { els.list.scrollTop = els.list.scrollHeight; } catch {}
      }
    }

    function start(){
      t0 = Date.now();
      try {
        if (els.list) els.list.innerHTML = '';
        if (els.elapsed) els.elapsed.textContent = '0s';
        if (els.clock) els.clock.textContent = new Date().toLocaleTimeString();
        if (els.bar) els.bar.style.width = '10%';
        if (els.meter) els.meter.value = 10;
      } catch {}
      tickClock();
      clockTimer = setInterval(tickClock, 1000);
      setStep('Preparing…', 10);
    }

    function stop(){
      // Persistent progress card: leave the final state visible in the
      // aside rather than hiding the block.
      try { if (clockTimer) clearInterval(clockTimer); } catch {}
    }

    return { setStep, start, stop };
  }

  // Shows the server's timing breakdown: one line per render step, then a
  // summary of the request phases.
  async function showMetrics(progress, metrics){
    if (!metrics) return;
    const steps = Array.isArray(metrics.steps) ? metrics.steps : [];
    let pct = 60;
    for (const step of steps) {
      pct += 30 / steps.length;
      progress.setStep(`${step.name} ${step.elapsed_ms} ms`, pct);
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    const parts = [];
    for (const [label, key] of METRIC_LABELS) {
      const val = metrics[key];
      if (val !== null && val !== undefined) parts.push(`${label} ${val} ms`);
    }
    if (parts.length) progress.setStep(parts.join(' • '), 90);
  }

  // Follows /api/progress/stream for this plugin and calls onEnd when it
  // reports that the render finished or failed.
  function attachLiveProgress(progress, pluginId, onEnd){
    const inactive = { close(){}, hasRecent(){ return false; }, ended(){ return false; } };
    if (!pluginId || typeof EventSource === 'undefined') return inactive;
    let source = null;
    let lastLiveAt = 0;
    let endedAt = 0;
    const startedAt = Date.now() / 1000 - 5;
    const labels = {
      queued: 'Queued on device',
      running: 'Preparing plugin',
      done: 'Done',
      error: 'Failed — see error above'
    };
    const pctByState = { queued: 15, running: 25, step: 50, done: 100, error: 100 };

    function applyEvent(payload){
      if (!payload || payload.plugin_id !== pluginId) return;
      if (typeof payload.ts === 'number' && payload.ts < startedAt) return;
      let text = payload.step || labels[payload.state] || null;
      if (payload.state === 'error' && payload.error) {
        text = `Failed — ${payload.error}`;
      }
      if (!text) return;
      lastLiveAt = Date.now();
      progress.setStep(text, pctByState[payload.state] || 55);
      if (payload.state === 'done' || payload.state === 'error') {
        endedAt = lastLiveAt;
        try { source?.close(); } catch {}
        if (typeof onEnd === 'function') onEnd();
      }
    }

    try {
      source = new EventSource('/api/progress/stream');
      ['queued', 'running', 'step', 'done', 'error'].forEach((eventName) => {
        source.addEventListener(eventName, (event) => {
          try { applyEvent(JSON.parse(event.data || '{}')); } catch {}
        });
      });
    } catch (e) {
      console.warn('Live progress stream unavailable:', e);
      return inactive;
    }
    return {
      close(){ try { source?.close(); } catch {} },
      hasRecent(){ return lastLiveAt > 0 && Date.now() - lastLiveAt < 3000; },
      ended(){ return endedAt > 0; }
    };
  }

  // A sleep that can be cut short, so the poll loop reacts as soon as the
  // live stream reports the end of a render.
  function createWaker(){
    let wakeNow = null;
    return {
      sleep(ms){
        return new Promise((resolve) => {
          const timer = setTimeout(finish, ms);
          function finish(){
            clearTimeout(timer);
            wakeNow = null;
            resolve();
          }
          wakeNow = finish;
        });
      },
      wake(){ if (wakeNow) wakeNow(); }
    };
  }

  function nextPollDelay(live){
    if (live.ended()) return POLL_MS_AFTER_LIVE_END;
    if (live.hasRecent()) return POLL_MS_WHILE_LIVE;
    return POLL_MS;
  }

  // Polls the background job until it is done or failed. Returns the job
  // record, or null when the request timed out first.
  async function pollJob({ jobId, signal, progress, live, waker }){
    let polls = 0;
    while (!signal.aborted) {
      await waker.sleep(nextPollDelay(live));
      if (signal.aborted) break;
      polls++;
      let jobInfo;
      try {
        const resp = await fetch('/api/job/' + jobId, { signal });
        jobInfo = await resp.json();
      } catch (pollErr) {
        if (pollErr.name === 'AbortError') break;
        console.warn('Poll error:', pollErr);
        continue;
      }
      const status = jobInfo?.status;
      if (status === 'done' || status === 'error') return jobInfo;
      // 'pending' or 'running': keep polling. Without live steps, the bar
      // creeps forward so the page doesn't look stuck.
      if (status === 'running' && !live.hasRecent()) {
        progress.setStep('Rendering (background)…', 40 + Math.min(polls, 50));
      }
    }
    return null;
  }

  function surfaceFieldError(result) {
    const message = result?.error || result?.message || "";
    const field = String(result?.field || "").toLowerCase();
    if (!message) return false;
    if (field && field !== "url") return false;
    if (!field && !/url/i.test(message)) return false;
    const input = document.querySelector("#settingsForm [name='url']");
    if (!input) return false;
    const group = input.closest(".form-group") || input.parentElement;
    const describedByTokens = (input.getAttribute("aria-describedby") || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    const fallbackId = input.id ? input.id + "-error" : "";
    let messageEl = null;
    for (const token of describedByTokens) {
      const candidate = document.getElementById(token);
      if (candidate?.classList.contains("validation-message")) {
        messageEl = candidate;
        break;
      }
    }
    if (!messageEl && fallbackId) messageEl = document.getElementById(fallbackId);
    input.setAttribute("aria-invalid", "true");
    group?.classList.add("has-error");
    group?.classList.remove("has-success");
    if (messageEl) {
      if (messageEl.id && !describedByTokens.includes(messageEl.id)) {
        describedByTokens.push(messageEl.id);
        input.setAttribute("aria-describedby", describedByTokens.join(" "));
      }
      messageEl.textContent = message;
      messageEl.style.display = "";
    } else if (group) {
      const fallback = document.createElement("span");
      fallback.className = "validation-message";
      fallback.setAttribute("role", "alert");
      if (fallbackId) {
        fallback.id = fallbackId;
        input.setAttribute("aria-describedby", fallback.id);
      }
      fallback.textContent = message;
      group.appendChild(fallback);
    }
    try { input.focus(); } catch {}
    return true;
  }

  // Picked files live in window.uploadedFiles ({fieldName: [File, ...]}) until
  // a request carries them, because the file input is cleared after each pick
  // so the same picker can add more files.
  function appendUploadedFiles(formData, uploadedFiles){
    Object.keys(uploadedFiles || {}).forEach(key => {
      (uploadedFiles[key] || []).forEach(f => formData.append(key, f));
    });
  }

  // Routes that store uploads reply with the stored paths (saved_files); the
  // upload widget swaps its pending files for those paths so the next save
  // keeps them instead of uploading another copy.
  function announceSavedUploads(savedFiles){
    if (!savedFiles || typeof savedFiles !== 'object' || !Object.keys(savedFiles).length) return;
    document.dispatchEvent(new CustomEvent('inkypi:uploads-saved', { detail: { savedFiles } }));
  }

  async function reportSuccess(progress, result, onAfterSuccess){
    await showMetrics(progress, result?.metrics);
    notify('success', `Success! ${result.message}`);
    announceSavedUploads(result?.saved_files);
    // The page refreshes its preview images here.
    if (typeof onAfterSuccess === 'function') {
      try { onAfterSuccess(); } catch(e){ console.error('onAfterSuccess callback error:', e); }
    }
  }

  function reportFailure(result){
    surfaceFieldError(result);
    notify('failure', `Error! ${result.error}`);
  }

  function requestTarget(action, urls, formData){
    if (action === 'add_to_playlist') {
      const scheduleData = {};
      for (const [k, v] of new FormData($('scheduleForm')).entries()) scheduleData[k] = v;
      formData.append('refresh_settings', JSON.stringify(scheduleData));
      return { url: urls.add_to_playlist, method: 'POST' };
    }
    if (action === 'update_instance') return { url: urls.update_instance, method: 'PUT' };
    if (action === 'update_now') return { url: urls.update_now, method: 'POST' };
    // NOTE: action === 'save_settings' is handled declaratively via HTMX on
    // the Save Settings button (JTN-506). It is intentionally no longer routed
    // through sendForm so validation errors can swap inline instead of firing
    // a toast.
    throw new Error(`Unknown plugin action: ${action}`);
  }

  async function sendForm({ action, urls, uploadedFiles, onAfterSuccess }){
    const loadingIndicator = $('loadingIndicator');
    const progress = initProgress();
    const formData = new FormData($('settingsForm'));
    let success = false;
    let result = null;
    let liveProgress = null;

    try {
      appendUploadedFiles(formData, uploadedFiles);
    } catch(e){
      console.warn('Failed to attach uploaded files:', e);
      notify('failure', 'Failed to attach uploaded files: ' + (e.message || e));
      return { success: false, result: null };
    }

    const { url, method } = requestTarget(action, urls, formData);

    if (loadingIndicator) loadingIndicator.style.display = 'block';
    progress.start();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      progress.setStep('Sending…', 30);
      // Update Now renders in the background, so the browser doesn't wait on
      // one long request.
      const headers = {};
      if (url === urls.update_now) headers['X-Async'] = 'true';
      const response = await fetch(url, { method, body: formData, signal: controller.signal, headers });

      if (response.status === 202) {
        // Background render: follow it until the job finishes.
        const accepted = await response.json();
        const waker = createWaker();
        liveProgress = attachLiveProgress(
          progress, String(formData.get('plugin_id') || ''), waker.wake
        );
        progress.setStep('Rendering (background)…', 40);
        const jobInfo = await pollJob({
          jobId: accepted.job_id,
          signal: controller.signal,
          progress,
          live: liveProgress,
          waker
        });
        if (jobInfo === null) {
          notify('failure', TIMEOUT_MESSAGE);
        } else if (jobInfo.status === 'done') {
          result = jobInfo.result || { success: true, message: 'Display updated' };
          await reportSuccess(progress, result, onAfterSuccess);
          success = true;
        } else {
          result = { error: jobInfo.error || 'Plugin render failed' };
          reportFailure(result);
        }
      } else {
        progress.setStep('Waiting (device)…', 60);
        result = await response.json();
        if (response.ok) {
          await reportSuccess(progress, result, onAfterSuccess);
          success = true;
        } else {
          reportFailure(result);
        }
      }
    } catch (e){
      console.error('Error in plugin form submission:', e);
      if (e.name === 'AbortError') {
        notify('failure', TIMEOUT_MESSAGE);
      } else if (e instanceof TypeError) {
        notify('failure', navigator.onLine === false
          ? 'You appear to be offline. Check your connection.'
          : 'Unable to reach the device. Check that InkyPi is running.');
      } else {
        notify('failure', 'An error occurred. Please try again.');
      }
    } finally {
      clearTimeout(timeoutId);
      try { liveProgress?.close(); } catch {}
      if (loadingIndicator) loadingIndicator.style.display = 'none';
      progress.setStep(success ? 'Done' : 'Failed — see error above', 100);
      progress.stop();
    }
    return { success, result };
  }

  // JTN-506: listen for HX-Trigger events from the HTMX-powered save path
  // and fire the existing response modal so user feedback is consistent with
  // the other plugin actions (update_now, update_instance, add_to_playlist).
  document.addEventListener('pluginSettingsSaved', (event) => {
    try {
      const detail = event && event.detail ? event.detail : {};
      const msg = detail.message || 'Settings saved.';
      notify('success', `Success! ${msg}`);
      announceSavedUploads(detail.saved_files);
    } catch (e) {
      console.warn('pluginSettingsSaved handler error:', e);
    }
  });

  // The HTMX Save Settings button sends #settingsForm, whose file inputs are
  // empty by then (see appendUploadedFiles), so add the picked files to the
  // request here. The button's hx-encoding makes htmx send them multipart.
  document.addEventListener('htmx:configRequest', (event) => {
    const detail = event && event.detail;
    if (!detail || !detail.elt || detail.elt.id !== 'savePluginSettingsBtn' || !detail.formData) return;
    try {
      appendUploadedFiles(detail.formData, window.uploadedFiles);
    } catch (e) {
      console.warn('Failed to attach uploaded files to save:', e);
    }
  });

  // Public API
  window.PluginForm = {
    sendForm
  };
})();

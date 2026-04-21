// Plugin Form Module
// Extracted from plugin.html to keep templates declarative.
(function(){
  'use strict';

  function $(id){ return document.getElementById(id); }

  function initProgress(){
    // Use InkyPiStore for progress state when available (JTN-502)
    const store = globalThis.InkyPiStore
      ? globalThis.InkyPiStore.createStore({ t0: 0, clockTimer: null, lastStepBase: '' })
      : null;

    let _t0 = 0, _clockTimer = null, _lastStepBase = '';
    function getT0(){ return store ? store.get('t0') : _t0; }
    function setT0(v){ if (store) { store.set({ t0: v }); } else { _t0 = v; } }
    function getClockTimer(){ return store ? store.get('clockTimer') : _clockTimer; }
    function setClockTimer(v){ if (store) { store.set({ clockTimer: v }); } else { _clockTimer = v; } }
    function getLastStepBase(){ return store ? store.get('lastStepBase') : _lastStepBase; }
    function setLastStepBase(v){ if (store) { store.set({ lastStepBase: v }); } else { _lastStepBase = v; } }

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
      const s = Math.floor(ms / 1000); const m = Math.floor(s / 60); const rem = s % 60; return m > 0 ? `${m}m ${rem}s` : `${s}s`; }
    function tickClock(){ try { if (els.clock) els.clock.textContent = new Date().toLocaleTimeString(); const elapsedMs = Date.now() - getT0(); if (els.elapsed) els.elapsed.textContent = fmtElapsed(elapsedMs); if (elapsedMs > 15000 && getLastStepBase() && els.text && !getLastStepBase().includes('Done') && !getLastStepBase().includes('Failed')) { els.text.textContent = getLastStepBase() + ' (' + fmtElapsed(elapsedMs) + ')'; } } catch(e){} }
    function setStep(text, pct){ setLastStepBase(text); if (els.block) { els.block.hidden = false; els.block.style.display = ''; } if (els.text) els.text.textContent = text; if (els.bar && typeof pct === 'number') { els.bar.style.width = pct + '%'; if (els.meter) els.meter.value = pct; }
      if (els.list){ const li = document.createElement('li'); const ts = document.createElement('time'); ts.dateTime = new Date().toISOString(); ts.textContent = new Date().toLocaleTimeString(); li.appendChild(ts); li.appendChild(document.createTextNode(' ' + text)); els.list.appendChild(li); try { els.list.scrollTop = els.list.scrollHeight; } catch(e){} }
    }
    function start(){ setT0(Date.now()); try { if (els.list) els.list.innerHTML = ''; if (els.elapsed) els.elapsed.textContent = '0s'; if (els.clock) els.clock.textContent = new Date().toLocaleTimeString(); if (els.bar) els.bar.style.width = '10%'; if (els.meter) els.meter.value = 10; } catch(e){} tickClock(); setClockTimer(setInterval(tickClock, 1000)); setStep('Preparing…', 10); }
    function stop(){ try { if (getClockTimer()) clearInterval(getClockTimer()); } catch(e){} /* Persistent progress card: leave the final state visible in the aside rather than hiding the block. */ }
    return { setStep, start, stop };
  }

  async function sendForm({ action, urls, uploadedFiles, onAfterSuccess }){
    const loadingIndicator = $('loadingIndicator');
    const progress = initProgress();
    const form = $('settingsForm');
    const scheduleForm = $('scheduleForm');
    const formData = new FormData(form);
    let success = false;
    let result = null;

    // append uploaded files
    try { Object.keys(uploadedFiles || {}).forEach(key => { (uploadedFiles[key] || []).forEach(f => formData.append(key, f)); }); } catch(e){ console.warn('Failed to append uploaded files:', e); if (window.showResponseModal) window.showResponseModal('failure', 'Failed to attach uploaded files: ' + (e.message || e)); return { success: false, result: null }; }

    let url = urls.update_now; let method = 'POST'; let clearFormOnSubmit = true;
    if (action === 'add_to_playlist'){
      url = urls.add_to_playlist; const scheduleFormData = new FormData(scheduleForm); const scheduleData = {}; for (const [k, v] of scheduleFormData.entries()) scheduleData[k] = v; formData.append('refresh_settings', JSON.stringify(scheduleData));
    } else if (action === 'update_instance'){
      url = urls.update_instance; method = 'PUT'; clearFormOnSubmit = false;
    }
    // NOTE: action === 'save_settings' is handled declaratively via HTMX on the
    // Save Settings button (JTN-506). It is intentionally no longer routed
    // through sendForm so validation errors can swap inline instead of firing
    // a toast.

    if (loadingIndicator) loadingIndicator.style.display = 'block';
    progress.start();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90000);
    try {
      progress.setStep('Sending…', 30);
      // Request async processing for update_now so the browser doesn't block
      const headers = {};
      if (action === 'update_now' || url === urls.update_now) { headers['X-Async'] = 'true'; }
      const response = await fetch(url, { method, body: formData, signal: controller.signal, headers });

      // -- Async job-queue flow for update_now (202 Accepted) --
      if (response.status === 202) {
        const accepted = await response.json();
        const jobId = accepted.job_id;
        progress.setStep('Rendering (background)…', 40);

        // Poll /api/job/<id> until done or error
        const POLL_INTERVAL_MS = 1000;
        const MAX_POLLS = 90; // 90s total
        let polls = 0;
        let jobDone = false;
        while (polls < MAX_POLLS) {
          await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
          polls++;
          if (controller.signal.aborted) break;
          try {
            const pollResp = await fetch('/api/job/' + jobId, { signal: controller.signal });
            const jobInfo = await pollResp.json();
            if (jobInfo.status === 'running') {
              progress.setStep('Rendering (background)…', 40 + Math.min(polls, 50));
            } else if (jobInfo.status === 'done') {
              result = jobInfo.result || { success: true, message: 'Display updated' };
              // metrics display
              const m = result && result.metrics || null;
              if (m && Array.isArray(m.steps) && m.steps.length){ let pct = 60; const inc = 30 / m.steps.length; for (const step of m.steps){ pct += inc; progress.setStep(`${step.name} ${step.elapsed_ms} ms`, pct); await new Promise(r => setTimeout(r, 50)); } }
              const parts = []; const add = (label, val) => { if (val !== null && val !== undefined) parts.push(`${label} ${val} ms`); };
              if (m){ add('Request', m.request_ms); add('Generate', m.generate_ms); add('Preprocess', m.preprocess_ms); add('Display', m.display_ms); }
              if (parts.length){ progress.setStep(parts.join(' • '), 90); }
              if (window.showResponseModal) window.showResponseModal('success', `Success! ${result.message}`);
              success = true;
              if (typeof onAfterSuccess === 'function') { try { onAfterSuccess(); } catch(e){ console.error('onAfterSuccess callback error:', e); } }
              jobDone = true;
              break;
            } else if (jobInfo.status === 'error') {
              result = { error: jobInfo.error || 'Plugin render failed' };
              if (window.showResponseModal) window.showResponseModal('failure', `Error! ${result.error}`);
              jobDone = true;
              break;
            }
            // status === 'pending' — keep polling
          } catch (pollErr) {
            if (pollErr.name === 'AbortError') break;
            console.warn('Poll error:', pollErr);
          }
        }
        if (!jobDone && !controller.signal.aborted) {
          if (window.showResponseModal) window.showResponseModal('failure', 'Request timed out. The plugin may still be processing \u2014 check back in a moment.');
        }
      } else {
        // -- Synchronous response (non-update_now routes) --
        progress.setStep('Waiting (device)…', 60);
        result = await response.json();
        if (response.ok){
          // metrics display
          const m = result && result.metrics || null;
          if (m && Array.isArray(m.steps) && m.steps.length){ let pct = 60; const inc = 30 / m.steps.length; for (const step of m.steps){ pct += inc; progress.setStep(`${step.name} ${step.elapsed_ms} ms`, pct); await new Promise(r => setTimeout(r, 50)); } }
          const parts = []; const add = (label, val) => { if (val !== null && val !== undefined) parts.push(`${label} ${val} ms`); };
          if (m){ add('Request', m.request_ms); add('Generate', m.generate_ms); add('Preprocess', m.preprocess_ms); add('Display', m.display_ms); }
          if (parts.length){ progress.setStep(parts.join(' • '), 90); }
          if (window.showResponseModal) window.showResponseModal('success', `Success! ${result.message}`);
          success = true;
          // Call the success callback to refresh images
          if (typeof onAfterSuccess === 'function') {
            try { onAfterSuccess(); } catch(e){ console.error('onAfterSuccess callback error:', e); }
          }
        } else {
          if (window.showResponseModal) window.showResponseModal('failure', `Error!  ${result.error}`);
        }
      }
    } catch (e){
      console.error('Error in plugin form submission:', e);
      console.error('Error stack:', e.stack);
      if (e.name === 'AbortError') {
        if (window.showResponseModal) window.showResponseModal('failure', 'Request timed out. The plugin may still be processing \u2014 check back in a moment.');
      } else if (e instanceof TypeError) {
        const msg = navigator.onLine === false
          ? 'You appear to be offline. Check your connection.'
          : 'Unable to reach the device. Check that InkyPi is running.';
        if (window.showResponseModal) window.showResponseModal('failure', msg);
      } else {
        if (window.showResponseModal) window.showResponseModal('failure', 'An error occurred. Please try again.');
      }
    } finally {
      clearTimeout(timeoutId);
      if (loadingIndicator) loadingIndicator.style.display = 'none';
      progress.setStep(success ? 'Done' : 'Failed \u2014 see error above', 100);
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
      if (window.showResponseModal) {
        window.showResponseModal('success', `Success! ${msg}`);
      }
    } catch (e) {
      console.warn('pluginSettingsSaved handler error:', e);
    }
  });

  // Public API
  window.PluginForm = {
    sendForm
  };
})();


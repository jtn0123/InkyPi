// Plugin Form Module
// Extracted from plugin.html to keep templates declarative.
(function(){
  'use strict';

  function $(id){ return document.getElementById(id); }

  function initProgress(){
    const state = {
      t0: 0,
      clockTimer: null,
      els: {
        block: $('requestProgress'),
        text: $('requestProgressText'),
        bar: $('requestProgressBar'),
        list: $('requestProgressList'),
        clock: $('requestProgressClock'),
        elapsed: $('requestProgressElapsed')
      }
    };
    function fmtElapsed(ms){
      const s = Math.floor(ms / 1000); const m = Math.floor(s / 60); const rem = s % 60; return m > 0 ? `${m}m ${rem}s` : `${s}s`; }
    function tickClock(){ try { if (state.els.clock) state.els.clock.textContent = new Date().toLocaleTimeString(); if (state.els.elapsed) state.els.elapsed.textContent = fmtElapsed(Date.now() - state.t0); } catch(e){} }
    function setStep(text, pct){ if (state.els.block) state.els.block.style.display = 'block'; if (state.els.text) state.els.text.textContent = text; if (state.els.bar && typeof pct === 'number') state.els.bar.style.width = pct + '%';
      if (state.els.list){ const li = document.createElement('li'); const ts = document.createElement('time'); ts.dateTime = new Date().toISOString(); ts.textContent = new Date().toLocaleTimeString(); li.appendChild(ts); li.appendChild(document.createTextNode(' ' + text)); state.els.list.appendChild(li); try { state.els.list.scrollTop = state.els.list.scrollHeight; } catch(e){} }
    }
    function start(){ state.t0 = Date.now(); try { if (state.els.list) state.els.list.innerHTML = ''; if (state.els.elapsed) state.els.elapsed.textContent = '0s'; if (state.els.clock) state.els.clock.textContent = new Date().toLocaleTimeString(); if (state.els.bar) state.els.bar.style.width = '10%'; } catch(e){} tickClock(); state.clockTimer = setInterval(tickClock, 1000); setStep('Preparing…', 10); }
    function stop(){ try { if (state.clockTimer) clearInterval(state.clockTimer); } catch(e){} setTimeout(() => { if (state.els.block) state.els.block.style.display = 'none'; }, 2000); }
    return { setStep, start, stop };
  }

  async function sendForm({ action, urls, uploadedFiles }){
    const loadingIndicator = $('loadingIndicator');
    const progress = initProgress();
    const form = $('settingsForm');
    const scheduleForm = $('scheduleForm');
    const formData = new FormData(form);
    let success = false;
    let result = null;

    // append uploaded files
    try { Object.keys(uploadedFiles || {}).forEach(key => { (uploadedFiles[key] || []).forEach(f => formData.append(key, f)); }); } catch(e){}

    let url = urls.update_now; let method = 'POST'; let clearFormOnSubmit = true;
    if (action === 'add_to_playlist'){
      url = urls.add_to_playlist; const scheduleFormData = new FormData(scheduleForm); const scheduleData = {}; for (const [k, v] of scheduleFormData.entries()) scheduleData[k] = v; formData.append('refresh_settings', JSON.stringify(scheduleData));
    } else if (action === 'update_instance'){
      url = urls.update_instance; method = 'PUT'; clearFormOnSubmit = false;
    } else if (action === 'save_settings'){
      url = urls.save_settings; clearFormOnSubmit = false;
    }

    if (loadingIndicator) loadingIndicator.style.display = 'block';
    progress.start();
    try {
      progress.setStep('Sending…', 30);
      const response = await fetch(url, { method, body: formData });
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
      } else {
        if (window.showResponseModal) window.showResponseModal('failure', `Error!  ${result.error}`);
      }
    } catch (e){
      console.error('Error in plugin form submission:', e);
      console.error('Error stack:', e.stack);
      if (window.showResponseModal) window.showResponseModal('failure', 'An error occurred while processing your request. Please try again.');
    } finally {
      if (loadingIndicator) loadingIndicator.style.display = 'none';
      progress.setStep('Done', 100);
      progress.stop();
    }
    return { success, result };
  }

  // Public API
  window.PluginForm = {
    sendForm
  };
})();



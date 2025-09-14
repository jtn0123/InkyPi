// Extracted playlist page logic from inline script in templates
// Expect a global PLAYLIST_CTX providing URLs and constants
// {
//   reorder_url: str,
//   delete_plugin_instance_url: str,
//   display_plugin_instance_url: str,
//   create_playlist_url: str,
//   update_playlist_base_url: str, // trailing slash
//   delete_playlist_base_url: str, // trailing slash
//   display_next_url: str,
//   device_tz_offset_min: number
// }

(function(){
    const C = window.PLAYLIST_CTX || {};
    const LAST_PROGRESS_KEY = 'INKYPI_LAST_PROGRESS';

    // Drag-and-drop reordering support
    let dragSrcEl = null;

    function handleDragStart(e){
        dragSrcEl = this;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', this.id);
        this.classList.add('dragging');
    }
    function handleDragOver(e){
        if (e.preventDefault) e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        return false;
    }
    function handleDrop(e){
        if (e.stopPropagation) e.stopPropagation();
        const srcId = e.dataTransfer.getData('text/plain');
        const srcEl = document.getElementById(srcId);
        if (srcEl && srcEl !== this){
            this.parentNode.insertBefore(srcEl, this.nextSibling);
            const container = this.closest('.playlist-item');
            const playlistName = container?.getAttribute('data-playlist-name');
            const ordered = Array.from(container.querySelectorAll('.plugin-item'))
                .map(el => ({ plugin_id: el.getAttribute('data-plugin-id'), name: el.getAttribute('data-instance-name') }));
            if (playlistName && ordered.length){
                fetch(C.reorder_url, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ playlist_name: playlistName, ordered })
                }).then(handleJsonResponse).then(j => {
                    if (!j || !j.success){
                        // already surfaced
                    } else {
                        sessionStorage.setItem("storedMessage", JSON.stringify({ type: "success", text: `Success! ${j.message}` }));
                    }
                }).catch(() => showResponseModal('failure', 'Error saving new order'));
            }
        }
        return false;
    }
    function handleDragEnd(){ this.classList.remove('dragging'); }

    function handleKeyReorder(e){
        if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
        e.preventDefault();
        const item = e.currentTarget;
        const parent = item.parentElement;
        if (!parent) return;
        let target = (e.key === 'ArrowUp') ? item.previousElementSibling : item.nextElementSibling;
        while (target && !target.classList.contains('plugin-item')){
            target = (e.key === 'ArrowUp') ? target.previousElementSibling : target.nextElementSibling;
        }
        if (!target) return;
        if (e.key === 'ArrowUp') parent.insertBefore(item, target); else parent.insertBefore(item, target.nextElementSibling);
        const container = item.closest('.playlist-item');
        const playlistName = container?.getAttribute('data-playlist-name');
        const ordered = Array.from(container.querySelectorAll('.plugin-item'))
            .map(el => ({ plugin_id: el.getAttribute('data-plugin-id'), name: el.getAttribute('data-instance-name') }));
        if (playlistName && ordered.length){
            fetch(C.reorder_url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ playlist_name: playlistName, ordered }) })
                .then(handleJsonResponse)
                .catch(() => showResponseModal('failure', 'Error saving new order'));
        }
        item.focus();
    }

    function enableDrag(container){
        const items = container.querySelectorAll('.plugin-item');
        items.forEach((item) => {
            if (!item.id) item.id = `plg-${Math.random().toString(36).slice(2)}`;
            item.draggable = true;
            item.addEventListener('dragstart', handleDragStart);
            item.addEventListener('dragover', handleDragOver);
            item.addEventListener('drop', handleDrop);
            item.addEventListener('dragend', handleDragEnd);
            item.tabIndex = 0;
            item.setAttribute('role', 'listitem');
            item.addEventListener('keydown', handleKeyReorder);
        });
    }

    async function deletePluginInstance(playlistName, pluginId, pluginInstance) {
        try {
            const response = await fetch(C.delete_plugin_instance_url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ playlist_name: playlistName, plugin_id: pluginId, plugin_instance: pluginInstance })
            });
            const result = await handleJsonResponse(response);
            if (response.ok && result && result.success){
                location.reload();
            }
        } catch (error) {
            console.error('Error:', error);
            alert('An error occurred while processing your request.');
        }
    }

    async function displayPluginInstance(playlistName, pluginId, pluginInstance, btnEl) {
        const loadingIndicator = document.getElementById(pluginInstance)?.querySelector('.loading-indicator');
        const progress = document.getElementById('globalProgress');
        const progressText = document.getElementById('globalProgressText');
        const progressBar = document.getElementById('globalProgressBar');
        const progressClock = document.getElementById('globalProgressClock');
        const progressElapsed = document.getElementById('globalProgressElapsed');
        const progressList = document.getElementById('globalProgressList');
        const t0 = Date.now();
        let clockTimer = null;
        function fmtElapsed(ms){
            const s = Math.floor(ms / 1000);
            const m = Math.floor(s / 60);
            const rem = s % 60;
            if (m > 0) return `${m}m ${rem}s`;
            return `${s}s`;
        }
        function tickClock(){
            try {
                if (progressClock) progressClock.textContent = new Date().toLocaleTimeString();
                if (progressElapsed) progressElapsed.textContent = fmtElapsed(Date.now() - t0);
            } catch(e){}
        }
        function addLog(line){
            if (!progressList) return;
            const li = document.createElement('li');
            const ts = document.createElement('time');
            ts.dateTime = new Date().toISOString();
            ts.textContent = new Date().toLocaleTimeString();
            li.appendChild(ts);
            li.appendChild(document.createTextNode(line));
            progressList.appendChild(li);
            try { progressList.scrollTop = progressList.scrollHeight; } catch(e){}
        }
        function setStep(text, pct){
            if (progress) progress.style.display = 'block';
            if (progressText) progressText.textContent = text;
            if (progressBar && typeof pct === 'number') progressBar.style.width = pct + '%';
            addLog(text);
        }
        if (loadingIndicator) loadingIndicator.style.display = 'block';
        if (btnEl) { btnEl.disabled = true; const sp = btnEl.querySelector('.btn-spinner'); if (sp) sp.style.display = 'inline-block'; }
        // Reset meta & log
        try { if (clockTimer) clearInterval(clockTimer); } catch(e){}
        try {
            if (progressList) progressList.innerHTML = '';
            if (progressElapsed) progressElapsed.textContent = '0s';
            if (progressClock) progressClock.textContent = new Date().toLocaleTimeString();
            if (progressBar) progressBar.style.width = '10%';
        } catch(e){}
        tickClock();
        clockTimer = setInterval(tickClock, 1000);
        setStep('Preparing…', 10);
        try {
            const response = await fetch(C.display_plugin_instance_url, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ playlist_name: playlistName, plugin_id: pluginId, plugin_instance: pluginInstance })
            });
            setStep('Waiting (device)…', 60);
            const result = await handleJsonResponse(response);
            if (response.ok && result && result.success) {
                if (result && result.metrics){
                    const m = result.metrics;
                    if (Array.isArray(m.steps) && m.steps.length){
                        let pct = 60;
                        const inc = 30 / m.steps.length;
                        for (const [name, ms] of m.steps){
                            pct += inc;
                            setStep(`${name} ${ms} ms`, pct);
                            await new Promise(r => setTimeout(r, 50));
                        }
                    }
                    const text = `Request ${m.request_ms ?? '-'} ms • Generate ${m.generate_ms ?? '-'} ms • Preprocess ${m.preprocess_ms ?? '-'} ms • Display ${m.display_ms ?? '-'} ms`;
                    if (progressText) progressText.textContent = text;
                    addLog(text);
                }
                setStep('Display updating…', 90);
                sessionStorage.setItem("storedMessage", JSON.stringify({ type: "success", text: `Success! ${result.message}` }));
                location.reload();
            }
        } catch (error) {
            console.error('Error:', error);
            alert('An error occurred while processing your request.');
        } finally {
            if (loadingIndicator) loadingIndicator.style.display = 'none';
            if (btnEl) { btnEl.disabled = false; const sp = btnEl.querySelector('.btn-spinner'); if (sp) sp.style.display = 'none'; }
            setStep('Done', 100);
            try { if (clockTimer) clearInterval(clockTimer); } catch(e){}
            try {
                const lines = Array.from(progressList ? progressList.querySelectorAll('li') : [], li => li.textContent || '');
                const data = {
                    finishedAtIso: new Date().toISOString(),
                    summary: progressText ? progressText.textContent : 'Done',
                    lines,
                    ctx: { page: 'playlist', playlist: playlistName, pluginId, instance: pluginInstance }
                };
                sessionStorage.setItem(LAST_PROGRESS_KEY, JSON.stringify(data));
            } catch(e){}
            setTimeout(() => { if (progress) progress.style.display = 'none'; }, 2000);
        }
    }

    function openCreateModal() {
        document.getElementById("modalTitle").textContent = "New Playlist";
        document.getElementById("playlist_name").value = "";
        document.getElementById("editingPlaylistName").value = "";
        document.getElementById("start_time").value = "00:00";
        document.getElementById("end_time").value = "24:00";
        document.getElementById("saveButton").setAttribute("onclick", "createPlaylist()")
        document.getElementById("deleteButton").classList.add("hidden");
        document.getElementById("playlistModal").style.display = "block";
    }

    function openEditModal(playlistName, startTime, endTime, cycleMinutes) {
        document.getElementById("modalTitle").textContent = "Update Playlist";
        document.getElementById("playlist_name").value = playlistName;
        document.getElementById("editingPlaylistName").value = playlistName;
        document.getElementById("start_time").value = startTime;
        document.getElementById("end_time").value = endTime;
        const cycleInput = document.getElementById('cycle_minutes');
        if (cycleInput){ cycleInput.value = cycleMinutes || ''; }
        document.getElementById("saveButton").setAttribute("onclick", "updatePlaylist()")
        document.getElementById("deleteButton").classList.remove("hidden");
        document.getElementById("playlistModal").style.display = "block";
    }

    function openModal() { const modal = document.getElementById('playlistModal'); modal.style.display = 'block'; }
    function closeModal() { const modal = document.getElementById('playlistModal'); modal.style.display = 'none'; }

    // Device cadence modal helpers
    function openDeviceCycleModal(){
        try {
            const input = document.getElementById('device_cycle_minutes');
            if (input) input.value = (C.device_cycle_minutes || 60);
        } catch(e){}
        const m = document.getElementById('deviceCycleModal');
        if (m) m.style.display = 'block';
    }
    function closeDeviceCycleModal(){
        const m = document.getElementById('deviceCycleModal');
        if (m) m.style.display = 'none';
    }
    async function saveDeviceCycle(){
        const input = document.getElementById('device_cycle_minutes');
        const minutes = parseInt((input?.value || '').trim(), 10);
        if (!minutes || minutes < 1 || minutes > 1440) { showResponseModal('failure', 'Enter minutes between 1 and 1440'); return; }
        try{
            const resp = await fetch(C.update_device_cycle_url, { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ minutes }) });
            const j = await handleJsonResponse(resp);
            if (resp.ok && j && j.success){ closeDeviceCycleModal(); location.reload(); }
        } catch(e){ showResponseModal('failure', 'Failed saving cadence'); }
    }

    async function createPlaylist() {
        let playlistName = document.getElementById("playlist_name").value.trim();
        let startTime = document.getElementById("start_time").value;
        let endTime = document.getElementById("end_time").value;
        try {
            const response = await fetch(C.create_playlist_url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ playlist_name: playlistName, start_time: startTime, end_time: endTime }) });
            const result = await handleJsonResponse(response);
            if (response.ok && result && result.success){ closeModal(); location.reload(); }
        } catch (error) { console.error("Error:", error); alert('An error occurred while processing your request.'); }
    }

    async function updatePlaylist() {
        let oldName = document.getElementById("editingPlaylistName").value;
        let newName = document.getElementById("playlist_name").value;
        let startTime = document.getElementById("start_time").value;
        let endTime = document.getElementById("end_time").value;
        let cycleMinutes = document.getElementById('cycle_minutes').value;
        try {
            const response = await fetch(C.update_playlist_base_url + oldName, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_name: newName, start_time: startTime, end_time: endTime, cycle_minutes: cycleMinutes || null }) });
            const result = await handleJsonResponse(response);
            if (response.ok && result && result.success){ closeModal(); location.reload(); }
        } catch (error) { console.error("Error:", error); alert('An error occurred while processing your request.'); }
    }

    async function deletePlaylist() {
        let name = document.getElementById("editingPlaylistName").value;
        try {
            const response = await fetch(C.delete_playlist_base_url + name, { method: "DELETE" });
            const result = await handleJsonResponse(response);
            if (response.ok && result && result.success){ closeModal(); location.reload(); }
        } catch (error) { console.error("Error:", error); alert('An error occurred while processing your request.'); }
    }

    async function deletePlaylistQuick(name){
        if (!confirm(`Delete playlist '${name}'?`)) return;
        try {
            const response = await fetch(C.delete_playlist_base_url + name, { method: "DELETE" });
            const result = await handleJsonResponse(response);
            if (response.ok && result && result.success){ location.reload(); }
        } catch (e){ alert('Failed to delete playlist'); }
    }

    async function displayNextInPlaylist(name){
        try{
            const resp = await fetch(C.display_next_url, { method:'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ playlist_name: name }) });
            const j = await handleJsonResponse(resp);
            if (resp.ok && j && j.success){ setTimeout(() => { location.reload(); }, 500); }
        } catch(e){ showResponseModal('failure', 'Failed to trigger display'); }
    }

    function populateTimeOptions() {
        let startSelect = document.getElementById("start_time");
        let endSelect = document.getElementById("end_time");
        startSelect.innerHTML = "";
        endSelect.innerHTML = "";
        for (let hour = 0; hour < 24; hour++) {
            for (let minutes of [0, 15, 30, 45]) {
                let time = hour.toString().padStart(2, '0') + ":" + minutes.toString().padStart(2, '0');
                startSelect.innerHTML += `<option value="${time}">${time}</option>`;
                endSelect.innerHTML += `<option value="${time}">${time}</option>`;
            }
        }
        startSelect.innerHTML += `<option value="24:00">24:00</option>`;
        endSelect.innerHTML += `<option value="24:00">24:00</option>`;
    }

    function initDeviceClock(){
        const val = document.getElementById('currentTimeValue');
        if (!val) return;
        function render(){
            try {
                const now = new Date();
                const browserOffsetMin = -now.getTimezoneOffset();
                const adjustMs = ((C.device_tz_offset_min || 0) - browserOffsetMin) * 60000;
                const devNow = new Date(now.getTime() + adjustMs);
                val.textContent = devNow.toLocaleString(undefined, { hour12: false });
            } catch(e) {}
        }
        setInterval(render, 1000);
        render();
    }

    function renderNextIn(){
        document.querySelectorAll('.plugin-item').forEach(item => {
            const infoEl = item.querySelector('.plugin-info');
            if (!infoEl) return;
            const intervalSecAttr = item.getAttribute('data-interval-sec');
            const lastIsoAttr = item.getAttribute('data-latest-iso');
            const intervalSec = intervalSecAttr ? parseInt(intervalSecAttr, 10) : NaN;
            if (!intervalSec || isNaN(intervalSec)) return;
            const lastDate = (() => { try { return lastIsoAttr ? new Date(lastIsoAttr) : null; } catch(_){ return null; } })();
            if (!lastDate) return;
            const nextTs = lastDate.getTime() + (intervalSec * 1000);
            const deltaMs = nextTs - Date.now();
            const nextEl = infoEl.querySelector('.latest-refresh');
            if (nextEl){
                if (deltaMs > 0){
                    const mins = Math.round(deltaMs / 60000);
                    if (mins < 60){ nextEl.textContent = `Refreshed • Next in ${mins} min`; }
                    else { const hrs = Math.floor(mins / 60); const rem = mins % 60; nextEl.textContent = `Refreshed • Next in ${hrs}h ${rem}m`; }
                }
            }
        });
    }

    function init(){
        populateTimeOptions();
        document.querySelectorAll('.playlist-item .plugin-list').forEach(enableDrag);
        // Bind header buttons
        const newBtn = document.getElementById('newPlaylistBtn');
        if (newBtn){ newBtn.addEventListener('click', () => openCreateModal()); }
        document.querySelectorAll('.edit-playlist-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const el = e.currentTarget;
                const name = el.getAttribute('data-playlist-name');
                const st = el.getAttribute('data-start-time');
                const et = el.getAttribute('data-end-time');
                const cm = el.getAttribute('data-cycle-minutes');
                openEditModal(name, st, et, cm);
            });
        });
        document.querySelectorAll('.run-next-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const name = e.currentTarget.getAttribute('data-playlist');
                displayNextInPlaylist(name);
            });
        });
        document.querySelectorAll('.delete-playlist-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const name = e.currentTarget.getAttribute('data-playlist');
                openDeletePlaylistModal(name);
            });
        });
        document.querySelectorAll('.delete-instance-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const t = e.currentTarget;
                openDeleteInstanceModal(t.getAttribute('data-playlist'), t.getAttribute('data-plugin-id'), t.getAttribute('data-instance'));
            });
        });
        document.querySelectorAll('.plugin-display-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const t = e.currentTarget;
                displayPluginInstance(t.getAttribute('data-playlist'), t.getAttribute('data-plugin-id'), t.getAttribute('data-instance'), t);
            });
        });
        
        // Device cadence editor
        const editCadence = document.getElementById('editDeviceCycleBtn');
        if (editCadence){ editCadence.addEventListener('click', openDeviceCycleModal); }

        // Click-to-zoom thumbnails
        document.querySelectorAll('.plugin-thumb').forEach(box => {
            try {
                box.style.cursor = 'zoom-in';
                box.setAttribute('role', 'button');
                box.setAttribute('tabindex', '0');
                const handler = () => {
                    const img = box.querySelector('img');
                    if (img && img.src && img.style.display !== 'none'){ openImagePreview(img.src, img.alt); }
                };
                box.addEventListener('click', handler);
                box.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); } });
            } catch(e){}
        });
        try {
            initDeviceClock();
            setInterval(renderNextIn, 60000);
            renderNextIn();
        } catch(e) { /* ignore */ }
    }

    if (document.readyState === 'loading'){
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // If injected after DOM is already ready (e.g., Playwright set_content), initialize immediately
        try { init(); } catch(e) {}
    }

    window.addEventListener("load", function () {
        const storedMessage = sessionStorage.getItem("storedMessage");
        if (storedMessage) {
            const { type, text } = JSON.parse(storedMessage);
            showResponseModal(type, text);
            sessionStorage.removeItem("storedMessage");
        }
    });

    function showLastProgressGlobal(){
        try {
            const raw = sessionStorage.getItem(LAST_PROGRESS_KEY);
            if (!raw) { try { showResponseModal('failure', 'No recent progress to show'); } catch(_){} return; }
            const data = JSON.parse(raw);
            const progress = document.getElementById('globalProgress');
            const textEl = document.getElementById('globalProgressText');
            const clockEl = document.getElementById('globalProgressClock');
            const elapsedEl = document.getElementById('globalProgressElapsed');
            const list = document.getElementById('globalProgressList');
            const bar = document.getElementById('globalProgressBar');
            if (list) {
                list.innerHTML = '';
                data.lines.forEach(line => {
                    const li = document.createElement('li');
                    const ts = document.createElement('time');
                    ts.textContent = new Date(data.finishedAtIso).toLocaleTimeString();
                    li.appendChild(ts);
                    li.appendChild(document.createTextNode(line));
                    list.appendChild(li);
                });
            }
            if (textEl) textEl.textContent = data.summary || 'Last run';
            if (clockEl) clockEl.textContent = new Date(data.finishedAtIso).toLocaleTimeString();
            if (elapsedEl) elapsedEl.textContent = '—';
            if (bar) bar.style.width = '100%';
            if (progress) progress.style.display = 'block';
        } catch(e){}
    }
    window.showLastProgressGlobal = showLastProgressGlobal;

    window.openCreateModal = openCreateModal;
    window.openEditModal = openEditModal;
    window.closeModal = closeModal;
    window.createPlaylist = createPlaylist;
    window.updatePlaylist = updatePlaylist;
    window.deletePlaylist = deletePlaylist;
    window.deletePlaylistQuick = deletePlaylistQuick;
    window.displayNextInPlaylist = displayNextInPlaylist;
    window.deletePluginInstance = deletePluginInstance;
    window.displayPluginInstance = displayPluginInstance;
    window.openDeviceCycleModal = openDeviceCycleModal;
    window.closeDeviceCycleModal = closeDeviceCycleModal;
    window.saveDeviceCycle = saveDeviceCycle;
    
    function openImagePreview(url, alt){
        const m = document.getElementById('imagePreviewModal');
        const img = document.getElementById('imagePreviewImg');
        if (!m || !img) return;
        img.src = url;
        img.alt = alt || 'Large preview';
        m.style.display = 'block';
        function esc(e){ if (e.key === 'Escape') { closeImagePreview(); document.removeEventListener('keydown', esc); } }
        document.addEventListener('keydown', esc);
    }
    function closeImagePreview(){
        const m = document.getElementById('imagePreviewModal');
        if (m) m.style.display = 'none';
    }
    window.openImagePreview = openImagePreview;
    window.closeImagePreview = closeImagePreview;

    // --- Delete confirm flows (replace confirm()) ---
    function showUndo(text){
        const sb = document.getElementById('undoSnackbar');
        const txt = document.getElementById('undoText');
        if (!sb || !txt) return;
        txt.textContent = text + ' Undo?';
        sb.style.display = 'inline-flex';
        const undo = document.getElementById('undoBtn');
        if (undo){
            undo.onclick = function(){ sb.style.display = 'none'; location.reload(); };
        }
        setTimeout(() => { sb.style.display = 'none'; }, 4000);
    }

    function openDeletePlaylistModal(name){
        const el = document.getElementById('deletePlaylistModal');
        const txt = document.getElementById('deletePlaylistText');
        const btn = document.getElementById('confirmDeletePlaylistBtn');
        if (!el || !txt || !btn) return;
        txt.textContent = `Delete playlist '${name}'?`;
        el.style.display = 'block';
        btn.onclick = async function(){
            try{
                const resp = await fetch(C.delete_playlist_base_url + name, { method:'DELETE' });
                const j = await handleJsonResponse(resp);
                if (resp.ok && j && j.success){
                    showUndo(`Playlist '${name}' deleted.`);
                    setTimeout(() => location.reload(), 800);
                }
            } catch(e){ showResponseModal('failure', 'Failed to delete playlist'); }
            closeDeletePlaylistModal();
        };
    }
    function closeDeletePlaylistModal(){ const el = document.getElementById('deletePlaylistModal'); if (el) el.style.display = 'none'; }

    function openDeleteInstanceModal(playlistName, pluginId, instanceName){
        const el = document.getElementById('deleteInstanceModal');
        const txt = document.getElementById('deleteInstanceText');
        const btn = document.getElementById('confirmDeleteInstanceBtn');
        if (!el || !txt || !btn) return;
        txt.textContent = `Delete instance '${instanceName}'?`;
        el.style.display = 'block';
        btn.onclick = async function(){
            try{
                const resp = await fetch(C.delete_plugin_instance_url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ playlist_name: playlistName, plugin_id: pluginId, plugin_instance: instanceName }) });
                const j = await handleJsonResponse(resp);
                if (resp.ok && j && j.success){
                    showUndo(`Instance '${instanceName}' deleted.`);
                    setTimeout(() => location.reload(), 800);
                }
            } catch(e){ showResponseModal('failure', 'Failed to delete instance'); }
            closeDeleteInstanceModal();
        };
    }
    function closeDeleteInstanceModal(){ const el = document.getElementById('deleteInstanceModal'); if (el) el.style.display = 'none'; }

    window.openDeletePlaylistModal = openDeletePlaylistModal;
    window.closeDeletePlaylistModal = closeDeletePlaylistModal;
    window.openDeleteInstanceModal = openDeleteInstanceModal;
    window.closeDeleteInstanceModal = closeDeleteInstanceModal;
})();

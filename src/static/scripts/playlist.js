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
        function setStep(text, pct){
            if (progress) progress.style.display = 'block';
            if (progressText) progressText.textContent = text;
            if (progressBar && typeof pct === 'number') progressBar.style.width = pct + '%';
        }
        if (loadingIndicator) loadingIndicator.style.display = 'block';
        if (btnEl) { btnEl.disabled = true; const sp = btnEl.querySelector('.btn-spinner'); if (sp) sp.style.display = 'inline-block'; }
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
                    const text = `Request ${m.request_ms ?? '-'} ms • Generate ${m.generate_ms ?? '-'} ms • Preprocess ${m.preprocess_ms ?? '-'} ms • Display ${m.display_ms ?? '-'} ms`;
                    if (progressText) progressText.textContent = text;
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
            setTimeout(() => { if (progress) progress.style.display = 'none'; }, 1200);
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

    document.addEventListener("DOMContentLoaded", function(){
        populateTimeOptions();
        document.querySelectorAll('.playlist-item .plugin-list').forEach(enableDrag);
        try {
            initDeviceClock();
            setInterval(renderNextIn, 60000);
            renderNextIn();
        } catch(e) { /* ignore */ }
    });

    window.addEventListener("load", function () {
        const storedMessage = sessionStorage.getItem("storedMessage");
        if (storedMessage) {
            const { type, text } = JSON.parse(storedMessage);
            showResponseModal(type, text);
            sessionStorage.removeItem("storedMessage");
        }
    });

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

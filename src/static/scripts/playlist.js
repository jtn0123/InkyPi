// Extracted playlist page logic from inline script in templates
// Requires: showResponseModal, handleJsonResponse (from response_modal.js, loaded first)
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
    // Configurable timing defaults (ms / px).
    const NEXT_IN_REFRESH_MS = 60000;      // 1 minute — countdown ticker interval
    const THUMB_PREFETCH_MARGIN = '200px';  // IntersectionObserver pre-load margin
    const PROGRESS_HIDE_DELAY_MS = 2000;    // delay before hiding progress panel

    const C = window.PLAYLIST_CTX || {};
    const mobileQuery = window.matchMedia ? window.matchMedia("(max-width: 768px)") : { matches: false, addEventListener() {} };
    const state = {
        expandedPlaylist: null,
        currentEditPlaylist: "",
        currentEditPluginId: "",
        currentEditInstance: "",
    };
    let playlistRefreshManager = null;

    // Track the element that triggered the most-recently opened modal so focus
    // can be restored when the modal closes.
    let _lastModalTrigger = null;

    function syncModalOpenState(){
        var ui = window.InkyPiUI;
        if (ui && ui.syncModalOpenState) return ui.syncModalOpenState();
        var open = document.querySelector('.modal.is-open, .thumbnail-preview-modal.is-open');
        document.body.classList.toggle('modal-open', !!open);
        // Block the page content from receiving pointer/keyboard events while any
        // modal is open.  The modal elements live outside #playlist-page-content
        // so they remain interactive.
        const pageContent = document.getElementById('playlist-page-content');
        if (pageContent) {
            if (open) {
                pageContent.setAttribute('inert', '');
            } else {
                pageContent.removeAttribute('inert');
            }
        }
    }

    function setModalOpen(modalId, open, triggerEl){
        const modal = document.getElementById(modalId);
        if (!modal) return;
        if (open && triggerEl) _lastModalTrigger = triggerEl;
        modal.hidden = !open;
        modal.style.display = open ? 'flex' : 'none';
        modal.classList.toggle('is-open', open);
        syncModalOpenState();
        if (open) {
            // Move focus to the first focusable element inside the modal
            const focusable = modal.querySelector(
                'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            );
            if (focusable) setTimeout(() => focusable.focus(), 0);
        } else {
            // Restore focus to the element that opened the modal
            if (_lastModalTrigger) {
                try { _lastModalTrigger.focus(); } catch(_) {}
                _lastModalTrigger = null;
            }
        }
    }

    function getOpenModalId(){
        const modalIds = [
            'deleteInstanceModal',
            'deletePlaylistModal',
            'displayNextConfirmModal',
            'thumbnailPreviewModal',
            'refreshSettingsModal',
            'deviceCycleModal',
            'playlistModal',
        ];
        return modalIds.find((modalId) => {
            const modal = document.getElementById(modalId);
            return modal && !modal.hidden;
        }) || null;
    }

    function closeModalById(modalId){
        switch (modalId) {
            case 'deleteInstanceModal':
                closeDeleteInstanceModal();
                return;
            case 'deletePlaylistModal':
                closeDeletePlaylistModal();
                return;
            case 'displayNextConfirmModal':
                closeDisplayNextConfirmModal();
                return;
            case 'thumbnailPreviewModal':
                closeThumbnailPreview();
                return;
            case 'refreshSettingsModal':
                closeRefreshModal();
                return;
            case 'deviceCycleModal':
                closeDeviceCycleModal();
                return;
            case 'playlistModal':
                closeModal();
                return;
            default:
                return;
        }
    }

    function buildProgressKey(ctx){
        try {
            if (ctx && ctx.page === 'playlist'){
                const pl = ctx.playlist || '_';
                const pid = ctx.pluginId || '_';
                const inst = ctx.instance || '_';
                return `INKYPI_LAST_PROGRESS:playlist:${pl}:${pid}:${inst}`;
            }
        } catch(e){}
        return 'INKYPI_LAST_PROGRESS';
    }

    function setPlaylistExpanded(item, expanded){
        const body = item?.querySelector('[data-playlist-body]');
        const toggle = item?.querySelector('[data-playlist-toggle]');
        if (!item || !body || !toggle) return;

        if (!mobileQuery.matches){
            body.hidden = false;
            item.classList.add('mobile-expanded');
            item.classList.remove('mobile-collapsed');
            toggle.textContent = toggle.getAttribute('data-expanded-label') || 'Hide';
            toggle.setAttribute('aria-expanded', 'true');
            return;
        }

        body.hidden = !expanded;
        item.classList.toggle('mobile-expanded', expanded);
        item.classList.toggle('mobile-collapsed', !expanded);
        toggle.textContent = expanded ? (toggle.getAttribute('data-expanded-label') || 'Hide') : (toggle.getAttribute('data-collapsed-label') || 'Open');
        toggle.setAttribute('aria-expanded', String(expanded));
        if (expanded){
            state.expandedPlaylist = item.getAttribute('data-playlist-name');
        }
    }

    function syncPlaylistCards(){
        const items = Array.from(document.querySelectorAll('[data-playlist-card]'));
        if (!items.length) return;
        if (!mobileQuery.matches){
            items.forEach((item) => setPlaylistExpanded(item, true));
            return;
        }
        const preferred = state.expandedPlaylist
            || items.find((item) => item.classList.contains('active'))?.getAttribute('data-playlist-name')
            || items[0].getAttribute('data-playlist-name');
        items.forEach((item) => {
            const isExpanded = item.getAttribute('data-playlist-name') === preferred;
            setPlaylistExpanded(item, isExpanded);
        });
    }

    function togglePlaylistCard(button){
        const item = button.closest('[data-playlist-card]');
        if (!item) return;
        const willExpand = item.classList.contains('mobile-collapsed') || !mobileQuery.matches;
        if (mobileQuery.matches && willExpand){
            document.querySelectorAll('[data-playlist-card]').forEach((card) => {
                if (card !== item) setPlaylistExpanded(card, false);
            });
        }
        setPlaylistExpanded(item, willExpand);
    }

    function showThumbnailPreview(playlistName, pluginId, pluginName, instanceName) {
        const img = document.getElementById('thumbnailPreviewImage');
        const info = document.getElementById('thumbnailPreviewInfo');
        if (!img || !info) return;
        img.src = `/plugin_instance_image/${encodeURIComponent(playlistName)}/${encodeURIComponent(pluginId)}/${encodeURIComponent(instanceName)}`;
        info.textContent = `Plugin: ${pluginName} | Instance: ${instanceName}`;
        setModalOpen('thumbnailPreviewModal', true);
    }

    function closeThumbnailPreview() {
        setModalOpen('thumbnailPreviewModal', false);
    }

    function openRefreshModal(playlistName, pluginId, instanceName, refreshSettings, triggerEl) {
        state.currentEditPlaylist = playlistName;
        state.currentEditPluginId = pluginId;
        state.currentEditInstance = instanceName;
        if (triggerEl) _lastModalTrigger = triggerEl;
        if (!playlistRefreshManager && typeof window.createRefreshSettingsManager === 'function') {
            playlistRefreshManager = window.createRefreshSettingsManager('refreshSettingsModal', 'modal');
        }
        if (playlistRefreshManager) {
            playlistRefreshManager.open({ refreshSettings });
            const modal = document.getElementById('refreshSettingsModal');
            if (modal) {
                modal.hidden = false;
                modal.classList.add('is-open');
                syncModalOpenState();
                // Move focus into the modal
                const focusable = modal.querySelector(
                    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
                );
                if (focusable) setTimeout(() => focusable.focus(), 0);
            }
        } else {
            setModalOpen('refreshSettingsModal', true);
        }
    }

    function closeRefreshModal() {
        if (playlistRefreshManager) {
            playlistRefreshManager.close();
            const modal = document.getElementById('refreshSettingsModal');
            if (modal) {
                modal.hidden = true;
                modal.classList.remove('is-open');
                syncModalOpenState();
            }
        } else {
            setModalOpen('refreshSettingsModal', false);
        }
        // Restore focus to the trigger element
        if (_lastModalTrigger) {
            try { _lastModalTrigger.focus(); } catch(_) {}
            _lastModalTrigger = null;
        }
    }

    async function saveRefreshSettings() {
        if (!playlistRefreshManager) return;
        await playlistRefreshManager.submit(async (formData) => {
            const data = new FormData();
            data.append('plugin_id', state.currentEditPluginId);
            data.append('refresh_settings', JSON.stringify(formData));
            const encodedInstance = encodeURIComponent(state.currentEditInstance);
            const response = await fetch(C.update_instance_base_url + encodedInstance, {
                method: 'PUT',
                body: data
            });
            const result = await response.json();
            if (response.ok) {
                sessionStorage.setItem("storedMessage", JSON.stringify({ type: "success", text: `Success! ${result.message}` }));
                location.reload();
            } else {
                throw new Error(result.error || 'Failed to update refresh settings');
            }
        });
    }

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
            const srcPlaylist = srcEl.closest('.playlist-item');
            const dstPlaylist = this.closest('.playlist-item');
            if (srcPlaylist !== dstPlaylist) return false;  // prevent cross-playlist drops
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
            showResponseModal('failure', 'An error occurred while processing your request.');
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
            const stripLeadingTime = (s) => { try { return s.replace(/^\s*\d{1,2}:\d{2}(?::\d{2})?\s*(AM|PM)?\s*/i, ''); } catch(_) { return s; } };
            const li = document.createElement('li');
            const ts = document.createElement('time');
            ts.dateTime = new Date().toISOString();
            ts.textContent = new Date().toLocaleTimeString();
            li.appendChild(ts);
            li.appendChild(document.createTextNode(' ' + stripLeadingTime(line)));
            progressList.appendChild(li);
            try { progressList.scrollTop = progressList.scrollHeight; } catch(e){}
        }
        function setStep(text, pct){
            if (progress) progress.style.display = 'block';
            if (progressText) progressText.textContent = text;
            if (progressBar && typeof pct === 'number') { progressBar.style.width = pct + '%'; progressBar.setAttribute('aria-valuenow', pct); }
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
            if (progressBar) { progressBar.style.width = '10%'; progressBar.setAttribute('aria-valuenow', 10); }
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
                    const m = result.metrics || {};
                    if (Array.isArray(m.steps) && m.steps.length){
                        let pct = 60;
                        const inc = 30 / m.steps.length;
                        for (const [name, ms] of m.steps){
                            pct += inc;
                            setStep(`${name} ${ms} ms`, pct);
                            await new Promise(r => setTimeout(r, 50));
                        }
                    }
                    const parts = [];
                    const add = (label, val) => { if (val !== null && val !== undefined) parts.push(`${label} ${val} ms`); };
                    add('Request', m.request_ms);
                    add('Generate', m.generate_ms);
                    add('Preprocess', m.preprocess_ms);
                    add('Display', m.display_ms);
                    if (parts.length){
                        const text = parts.join(' • ');
                        if (progressText) progressText.textContent = text;
                        addLog(text);
                    }
                }
                setStep('Display updating…', 90);
                sessionStorage.setItem("storedMessage", JSON.stringify({ type: "success", text: `Success! ${result.message}` }));
                location.reload();
            }
        } catch (error) {
            console.error('Error:', error);
            showResponseModal('failure', 'An error occurred while processing your request.');
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
                const key = buildProgressKey(data.ctx);
                localStorage.setItem(key, JSON.stringify(data));
                localStorage.setItem('INKYPI_LAST_PROGRESS', JSON.stringify(data));
            } catch(e){}
            setTimeout(() => { if (progress) progress.style.display = 'none'; }, PROGRESS_HIDE_DELAY_MS);
        }
    }

    function openCreateModal(triggerEl) {
        const modal = document.getElementById("playlistModal");
        document.getElementById("modalTitle").textContent = "New Playlist";
        document.getElementById("playlist_name").value = "";
        document.getElementById("editingPlaylistName").value = "";
        document.getElementById("start_time").value = "09:00";
        document.getElementById("end_time").value = "17:00";
        const cycleInput = document.getElementById('cycle_minutes');
        if (cycleInput) cycleInput.value = "";
        if (modal) modal.dataset.mode = "create";
        document.getElementById("deleteButton").classList.add("hidden");
        setModalOpen("playlistModal", true, triggerEl);
    }

    function openEditModal(playlistName, startTime, endTime, cycleMinutes, triggerEl) {
        const modal = document.getElementById("playlistModal");
        document.getElementById("modalTitle").textContent = "Update Playlist";
        document.getElementById("playlist_name").value = playlistName;
        document.getElementById("editingPlaylistName").value = playlistName;
        document.getElementById("start_time").value = _normaliseTimeForInput(startTime);
        document.getElementById("end_time").value = _normaliseTimeForInput(endTime);
        const cycleInput = document.getElementById('cycle_minutes');
        if (cycleInput){ cycleInput.value = cycleMinutes || ''; }
        if (modal) modal.dataset.mode = "edit";
        document.getElementById("deleteButton").classList.remove("hidden");
        setModalOpen("playlistModal", true, triggerEl);
    }

    function openModal() { setModalOpen('playlistModal', true); }
    function closeModal() { setModalOpen('playlistModal', false); }

    // Device cadence modal helpers
    function openDeviceCycleModal(){
        try {
            const input = document.getElementById('device_cycle_minutes');
            if (input) input.value = (C.device_cycle_minutes || 60);
        } catch(e){}
        setModalOpen('deviceCycleModal', true);
    }
    function closeDeviceCycleModal(){
        setModalOpen('deviceCycleModal', false);
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

    function _validatePlaylistName() {
        const input = document.getElementById("playlist_name");
        const error = document.getElementById("playlist-name-error");
        const name = (input.value || "").trim();
        if (!name) {
            input.setAttribute("aria-invalid", "true");
            if (error) error.textContent = "Playlist name is required";
            input.focus();
            return null;
        }
        if (name.length > 64) {
            input.setAttribute("aria-invalid", "true");
            if (error) error.textContent = "Name must be 64 characters or fewer";
            input.focus();
            return null;
        }
        input.setAttribute("aria-invalid", "false");
        if (error) error.textContent = "";
        return name;
    }

    function _scheduleFormState() {
        const form = document.getElementById('scheduleForm');
        return (globalThis.FormState && form) ? globalThis.FormState.attach(form) : null;
    }

    async function createPlaylist() {
        const fs = _scheduleFormState();
        if (fs) fs.clearErrors();
        let playlistName = _validatePlaylistName();
        if (!playlistName) return;
        let startTime = document.getElementById("start_time").value;
        let endTime = document.getElementById("end_time").value;
        const submit = async () => {
            try {
                const response = await fetch(C.create_playlist_url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ playlist_name: playlistName, start_time: startTime, end_time: endTime }) });
                const result = await handleJsonResponse(response);
                if (response.ok && result && result.success){
                    closeModal();
                    if (result.warning) { sessionStorage.setItem("storedMessage", JSON.stringify({ type: "warning", text: result.warning })); }
                    location.reload();
                } else if (fs && result && result.field_errors) {
                    fs.setFieldErrors(result.field_errors);
                }
            } catch (error) { console.error("Error:", error); showResponseModal('failure', 'An error occurred while processing your request.'); }
        };
        if (fs) await fs.run(submit); else await submit();
    }

    async function updatePlaylist() {
        const fs = _scheduleFormState();
        if (fs) fs.clearErrors();
        let oldName = document.getElementById("editingPlaylistName").value;
        let newName = _validatePlaylistName();
        if (!newName) return;
        let startTime = document.getElementById("start_time").value;
        let endTime = document.getElementById("end_time").value;
        let cycleMinutes = document.getElementById('cycle_minutes').value;
        const submit = async () => {
            try {
                const response = await fetch(C.update_playlist_base_url + encodeURIComponent(oldName), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_name: newName, start_time: startTime, end_time: endTime, cycle_minutes: cycleMinutes || null }) });
                const result = await handleJsonResponse(response);
                if (response.ok && result && result.success){
                    closeModal();
                    if (result.warning) { sessionStorage.setItem("storedMessage", JSON.stringify({ type: "warning", text: result.warning })); }
                    location.reload();
                } else if (fs && result && result.field_errors) {
                    fs.setFieldErrors(result.field_errors);
                }
            } catch (error) { console.error("Error:", error); showResponseModal('failure', 'An error occurred while processing your request.'); }
        };
        if (fs) await fs.run(submit); else await submit();
    }

    async function deletePlaylist() {
        let name = document.getElementById("editingPlaylistName").value;
        try {
            const response = await fetch(C.delete_playlist_base_url + encodeURIComponent(name), { method: "DELETE" });
            const result = await handleJsonResponse(response);
            if (response.ok && result && result.success){ closeModal(); location.reload(); }
        } catch (error) { console.error("Error:", error); showResponseModal('failure', 'An error occurred while processing your request.'); }
    }

    async function displayNextInPlaylist(name){
        const card = document.querySelector(`[data-playlist-name="${CSS.escape(name)}"]`);
        if (card && !card.querySelectorAll('.plugin-item').length) {
            showResponseModal('failure', 'Cannot display next — playlist has no items.');
            return;
        }
        try{
            const resp = await fetch(C.display_next_url, { method:'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ playlist_name: name }) });
            const j = await handleJsonResponse(resp);
            if (resp.ok && j && j.success){
                showResponseModal('success', 'Display updated — refreshing…');
                setTimeout(() => { location.reload(); }, 500);
            }
        } catch(e){ showResponseModal('failure', 'Failed to trigger display'); }
    }

    // Normalise a stored HH:MM (or "24:00") value to a form accepted by <input type="time">.
    function _normaliseTimeForInput(value) {
        if (!value) return value;
        if (value === "24:00") return "23:59";
        return value;
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
        document.querySelectorAll('.playlist-item .plugin-list').forEach(enableDrag);
        // Bind header buttons
        const newBtn = document.getElementById('newPlaylistBtn');
        if (newBtn){ newBtn.addEventListener('click', (e) => openCreateModal(e.currentTarget)); }
        document.querySelectorAll('[data-playlist-toggle]').forEach((button) => {
            button.addEventListener('click', () => togglePlaylistCard(button));
        });
        const saveBtn = document.getElementById('saveButton');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => {
                const mode = document.getElementById("playlistModal")?.dataset.mode || "create";
                if (mode === "edit") updatePlaylist(); else createPlaylist();
            });
        }
        document.getElementById('deleteButton')?.addEventListener('click', deletePlaylist);
        document.getElementById('closePlaylistModalBtn')?.addEventListener('click', closeModal);
        document.getElementById('closeRefreshModalBtn')?.addEventListener('click', closeRefreshModal);
        document.getElementById('saveRefreshSettingsBtn')?.addEventListener('click', saveRefreshSettings);
        document.getElementById('closeThumbnailPreviewBtn')?.addEventListener('click', closeThumbnailPreview);
        document.querySelectorAll('.edit-playlist-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const el = e.currentTarget;
                const name = el.getAttribute('data-playlist-name');
                const st = el.getAttribute('data-start-time');
                const et = el.getAttribute('data-end-time');
                const cm = el.getAttribute('data-cycle-minutes');
                openEditModal(name, st, et, cm, el);
            });
        });
        document.querySelectorAll('.run-next-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const el = e.currentTarget;
                const name = el.getAttribute('data-playlist');
                openDisplayNextConfirmModal(name, el);
            });
        });
        document.querySelectorAll('.delete-playlist-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const el = e.currentTarget;
                openDeletePlaylistModal(el.getAttribute('data-playlist'), el);
            });
        });
        document.querySelectorAll('.delete-instance-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const t = e.currentTarget;
                openDeleteInstanceModal(t.getAttribute('data-playlist'), t.getAttribute('data-plugin-id'), t.getAttribute('data-instance'), t);
            });
        });
        document.querySelectorAll('.refresh-settings-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const t = e.currentTarget;
                let refreshSettings = {};
                try {
                    refreshSettings = JSON.parse(t.getAttribute('data-refresh') || '{}');
                } catch (_err) {
                    refreshSettings = {};
                }
                openRefreshModal(
                    t.getAttribute('data-playlist'),
                    t.getAttribute('data-plugin-id'),
                    t.getAttribute('data-instance'),
                    refreshSettings,
                    t
                );
            });
        });
        document.querySelectorAll('.plugin-display-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const t = e.currentTarget;
                displayPluginInstance(t.getAttribute('data-playlist'), t.getAttribute('data-plugin-id'), t.getAttribute('data-instance'), t);
            });
        });
        document.querySelectorAll('.plugin-thumbnail-container').forEach(box => {
            box.addEventListener('click', (event) => {
                const t = event.currentTarget;
                showThumbnailPreview(
                    t.getAttribute('data-thumbnail-playlist'),
                    t.getAttribute('data-thumbnail-plugin'),
                    t.getAttribute('data-thumbnail-display-name'),
                    t.getAttribute('data-thumbnail-instance')
                );
            });
            box.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    box.click();
                }
            });
        });
        document.querySelectorAll('.plugin-thumbnail').forEach((img) => {
            img.addEventListener('load', () => {
                const skeleton = img.previousElementSibling;
                if (skeleton) skeleton.style.display = 'none';
                img.hidden = false;
            });
            img.addEventListener('error', () => {
                const container = img.closest('.plugin-thumbnail-container');
                if (container) container.hidden = true;
            });
        });
        
        // Cancel buttons on delete confirm modals
        document.getElementById('cancelDeletePlaylistBtn')?.addEventListener('click', closeDeletePlaylistModal);
        document.getElementById('cancelDeleteInstanceBtn')?.addEventListener('click', closeDeleteInstanceModal);
        document.getElementById('cancelDisplayNextBtn')?.addEventListener('click', closeDisplayNextConfirmModal);

        // Device cadence editor
        const editCadence = document.getElementById('editDeviceCycleBtn');
        if (editCadence){ editCadence.addEventListener('click', openDeviceCycleModal); }

        // Click-to-zoom thumbnails using shared Lightbox
        try {
            document.querySelectorAll('.plugin-thumb').forEach(box => {
                box.style.cursor = 'zoom-in';
                box.setAttribute('role', 'button');
                box.setAttribute('tabindex', '0');
            });
            if (window.Lightbox){
                window.Lightbox.bind('.plugin-thumb', {
                    getUrl: (el) => {
                        const img = el.querySelector('img');
                        return (img && img.src && img.style.display !== 'none') ? img.src : null;
                    },
                    getAlt: (el) => {
                        const img = el.querySelector('img');
                        return (img && img.alt) || 'Preview';
                    }
                });
            }
        } catch(e){}

        // Conditionally lazy-load thumbnails: HEAD check only when visible
        try {
            const thumbs = Array.from(document.querySelectorAll('.plugin-thumb img[data-src]'));
            const loadThumb = async (img) => {
                if (img.getAttribute('data-loaded') === '1') return;
                const url = img.getAttribute('data-src');
                if (!url) return;
                // Validate URL is a safe same-origin relative path before assigning
                // to img.src. Thumbnails are always served as site-relative paths
                // (e.g. "/static/images/..."), so we reject anything else to close
                // the js/xss-through-dom taint flow from DOM-sourced attribute.
                let safeUrl;
                try {
                    const parsed = new URL(url, window.location.origin);
                    if (parsed.origin === window.location.origin &&
                        (parsed.protocol === 'http:' || parsed.protocol === 'https:')) {
                        safeUrl = parsed.pathname + parsed.search;
                    }
                } catch(_) { /* invalid URL — leave safeUrl undefined */ }
                if (!safeUrl) {
                    img.style.display = 'none';
                    const sk0 = img.previousElementSibling; if (sk0) sk0.style.display = 'none';
                    img.setAttribute('data-loaded', '1');
                    return;
                }
                try {
                    const resp = await fetch(safeUrl, { method: 'HEAD' });
                    if (resp.ok) {
                        img.src = safeUrl;
                        img.style.display = '';
                        img.setAttribute('data-loaded', '1');
                    } else {
                        img.style.display = 'none';
                        const sk = img.previousElementSibling; if (sk) sk.style.display = 'none';
                        img.setAttribute('data-loaded', '1');
                    }
                } catch(_) {
                    img.style.display = 'none';
                    const sk = img.previousElementSibling; if (sk) sk.style.display = 'none';
                    img.setAttribute('data-loaded', '1');
                }
            };
            if ('IntersectionObserver' in window){
                const io = new IntersectionObserver((entries) => {
                    entries.forEach(entry => {
                        if (entry.isIntersecting){
                            const img = entry.target;
                            io.unobserve(img);
                            loadThumb(img);
                        }
                    });
                }, { rootMargin: mobileQuery.matches ? '50px' : THUMB_PREFETCH_MARGIN });
                thumbs.forEach(img => io.observe(img));
            } else {
                thumbs.forEach(loadThumb);
            }
        } catch(e){}
        try {
            initDeviceClock();
            setInterval(renderNextIn, NEXT_IN_REFRESH_MS);
            renderNextIn();
        } catch(e) { /* ignore */ }
        syncPlaylistCards();
        if (mobileQuery && typeof mobileQuery.addEventListener === 'function'){
            mobileQuery.addEventListener('change', syncPlaylistCards);
        }
        window.addEventListener('click', (event) => {
            if (event.target?.id === 'playlistModal') closeModal();
            if (event.target?.id === 'refreshSettingsModal') closeRefreshModal();
            if (event.target?.id === 'thumbnailPreviewModal') closeThumbnailPreview();
            if (event.target?.id === 'deviceCycleModal') closeDeviceCycleModal();
            if (event.target?.id === 'deletePlaylistModal') closeDeletePlaylistModal();
            if (event.target?.id === 'deleteInstanceModal') closeDeleteInstanceModal();
            if (event.target?.id === 'displayNextConfirmModal') closeDisplayNextConfirmModal();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape') return;
            const modalId = getOpenModalId();
            if (!modalId) return;
            event.preventDefault();
            closeModalById(modalId);
        });
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
            try {
                const { type, text } = JSON.parse(storedMessage);
                showResponseModal(type, text);
            } catch(e) {}
            sessionStorage.removeItem("storedMessage");
        }
    });

    function showLastProgressGlobal(){
        try {
            // Try any playlist-context key first; fallback to global
            let data = null;
            for (let i = 0; i < localStorage.length; i++){
                const k = localStorage.key(i);
                if (k && k.startsWith('INKYPI_LAST_PROGRESS:playlist:')){
                    try { data = JSON.parse(localStorage.getItem(k)); } catch(_){}
                }
            }
            if (!data){
                const raw = localStorage.getItem('INKYPI_LAST_PROGRESS');
                if (raw) data = JSON.parse(raw);
            }
            if (!data) { try { showResponseModal('failure', 'No recent progress to show'); } catch(_){} return; }
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
    window.showThumbnailPreview = showThumbnailPreview;
    window.closeThumbnailPreview = closeThumbnailPreview;
    window.openRefreshModal = openRefreshModal;
    window.closeRefreshModal = closeRefreshModal;
    window.saveRefreshSettings = saveRefreshSettings;

    window.openCreateModal = openCreateModal;
    window.openEditModal = openEditModal;
    window.closeModal = closeModal;
    window.createPlaylist = createPlaylist;
    window.updatePlaylist = updatePlaylist;
    window.deletePlaylist = deletePlaylist;
    window.displayNextInPlaylist = displayNextInPlaylist;
    window.deletePluginInstance = deletePluginInstance;
    window.displayPluginInstance = displayPluginInstance;
    window.openDeviceCycleModal = openDeviceCycleModal;
    window.closeDeviceCycleModal = closeDeviceCycleModal;
    window.saveDeviceCycle = saveDeviceCycle;
    
    // Use shared Lightbox API instead of local implementations

    // --- Delete confirm flows ---
    function openDeletePlaylistModal(name, triggerEl){
        const el = document.getElementById('deletePlaylistModal');
        const txt = document.getElementById('deletePlaylistText');
        const btn = document.getElementById('confirmDeletePlaylistBtn');
        if (!el || !txt || !btn) return;
        txt.textContent = `Delete playlist '${name}'?`;
        setModalOpen('deletePlaylistModal', true, triggerEl);
        btn.onclick = async function(){
            try{
                const resp = await fetch(C.delete_playlist_base_url + encodeURIComponent(name), { method:'DELETE' });
                const j = await handleJsonResponse(resp);
                if (resp.ok && j && j.success){ location.reload(); }
            } catch(e){ showResponseModal('failure', 'Failed to delete playlist'); }
            closeDeletePlaylistModal();
        };
    }
    function closeDeletePlaylistModal(){ setModalOpen('deletePlaylistModal', false); }

    function openDeleteInstanceModal(playlistName, pluginId, instanceName, triggerEl){
        const el = document.getElementById('deleteInstanceModal');
        const txt = document.getElementById('deleteInstanceText');
        const btn = document.getElementById('confirmDeleteInstanceBtn');
        if (!el || !txt || !btn) return;
        txt.textContent = `Delete instance '${instanceName}'?`;
        setModalOpen('deleteInstanceModal', true, triggerEl);
        btn.onclick = async function(){
            try{
                const resp = await fetch(C.delete_plugin_instance_url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ playlist_name: playlistName, plugin_id: pluginId, plugin_instance: instanceName }) });
                const j = await handleJsonResponse(resp);
                if (resp.ok && j && j.success){ location.reload(); }
            } catch(e){ showResponseModal('failure', 'Failed to delete instance'); }
            closeDeleteInstanceModal();
        };
    }
    function closeDeleteInstanceModal(){ setModalOpen('deleteInstanceModal', false); }

    function openDisplayNextConfirmModal(name, triggerEl){
        const el = document.getElementById('displayNextConfirmModal');
        const txt = document.getElementById('displayNextConfirmText');
        const btn = document.getElementById('confirmDisplayNextBtn');
        if (!el || !txt || !btn) {
            // Fallback: if the modal isn't present for any reason, fire the action directly.
            displayNextInPlaylist(name);
            return;
        }
        txt.textContent = `Advance '${name}' to the next plugin now?`;
        setModalOpen('displayNextConfirmModal', true, triggerEl);
        btn.onclick = async function(){
            closeDisplayNextConfirmModal();
            await displayNextInPlaylist(name);
        };
    }
    function closeDisplayNextConfirmModal(){ setModalOpen('displayNextConfirmModal', false); }

    window.openDeletePlaylistModal = openDeletePlaylistModal;
    window.closeDeletePlaylistModal = closeDeletePlaylistModal;
    window.openDeleteInstanceModal = openDeleteInstanceModal;
    window.closeDeleteInstanceModal = closeDeleteInstanceModal;
    window.openDisplayNextConfirmModal = openDisplayNextConfirmModal;
    window.closeDisplayNextConfirmModal = closeDisplayNextConfirmModal;
})();

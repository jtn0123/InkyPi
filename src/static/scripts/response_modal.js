// Enhanced toast notification system.
// Everything here is private to this file except the namespace and the three
// names other scripts call bare (biome.json lists them under
// javascript.globals). Requests go through fetchJson (fetch_json.js); pages
// toast its result or InkyPiHttp.errorMessage(error) themselves.
(function () {
    "use strict";

    // Configurable timing defaults (ms).
    const TOAST_DURATION_MS = 5000;
    const TOAST_ERROR_DURATION_MS = 8000;
    const TOAST_FADE_MS = 300;

    let toastContainer = null;
    let toastCounter = 0;

    function ensureToastContainer() {
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container';
            toastContainer.setAttribute('aria-live', 'polite');
            toastContainer.setAttribute('aria-label', 'Notifications');
            document.body.appendChild(toastContainer);
        }
        return toastContainer;
    }

    const MAX_VISIBLE_TOASTS = 3;

    function dismissStaleErrors() {
        const container = ensureToastContainer();
        const existingErrors = Array.from(container.querySelectorAll('.toast.error'));
        existingErrors.forEach(el => closeToast(el.id));
    }

    function showToast(status, message, duration = TOAST_DURATION_MS) {
        const container = ensureToastContainer();
        const toastId = `toast-${++toastCounter}`;

        // Dismiss stale error toasts when showing any new toast (error or success).
        // This prevents stale validation messages from lingering after a successful
        // retry and stops error toasts from stacking across rapid save attempts.
        dismissStaleErrors();

        // Enforce stack limit — remove oldest toasts beyond MAX_VISIBLE_TOASTS
        while (container.children.length >= MAX_VISIBLE_TOASTS) {
            const oldest = container.firstElementChild;
            if (oldest) oldest.remove();
        }

        // Resolve effective duration: errors use TOAST_ERROR_DURATION_MS by default
        const effectiveDuration = (status === 'error' && duration === TOAST_DURATION_MS)
            ? TOAST_ERROR_DURATION_MS
            : duration;

        const toast = document.createElement('div');
        toast.className = `toast ${status}`;
        toast.id = toastId;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', status === 'error' ? 'assertive' : 'polite');

        const iconMap = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ⓘ'
        };

        const iconEl = document.createElement('div');
        iconEl.className = 'toast-icon';
        iconEl.textContent = iconMap[status] || iconMap.info;

        const contentEl = document.createElement('div');
        contentEl.className = 'toast-content';
        contentEl.textContent = message;

        const closeBtn = document.createElement('button');
        closeBtn.className = 'toast-close';
        closeBtn.setAttribute('aria-label', 'Close notification');
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', () => closeToast(toastId));

        toast.appendChild(iconEl);
        toast.appendChild(contentEl);
        toast.appendChild(closeBtn);

        // Add countdown progress bar for auto-closing toasts
        if (effectiveDuration > 0) {
            const progress = document.createElement('div');
            progress.className = 'toast-progress';
            progress.style.animationDuration = `${effectiveDuration}ms`;
            toast.appendChild(progress);
        }

        container.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        // Auto-close after effectiveDuration
        if (effectiveDuration > 0) {
            setTimeout(() => closeToast(toastId), effectiveDuration);
        }

        return toastId;
    }

    function closeToast(toastId) {
        const toast = document.getElementById(toastId);
        if (toast) {
            toast.classList.remove('show');
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, TOAST_FADE_MS);
        }
    }

    // Older name for showToast that many pages call. "failure" means "error".
    function showResponseModal(status, message) {
        return showToast(status === 'failure' ? 'error' : status, message);
    }

    function showError(message, duration) {
        return showToast('error', message, duration);
    }

    globalThis.InkyPiToast = Object.freeze({
        close: closeToast,
        show: showToast,
        showError,
        showResponseModal,
    });
    globalThis.showToast = showToast;
    globalThis.showResponseModal = showResponseModal;
    globalThis.showError = showError;
})();

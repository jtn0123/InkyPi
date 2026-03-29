// Enhanced toast notification system
// Configurable timing defaults (ms).
const TOAST_DURATION_MS = 5000;
const MODAL_AUTO_CLOSE_MS = 10000;
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

function showToast(status, message, duration = TOAST_DURATION_MS) {
    const container = ensureToastContainer();
    const toastId = `toast-${++toastCounter}`;

    // Enforce stack limit — remove oldest toasts beyond MAX_VISIBLE_TOASTS
    while (container.children.length >= MAX_VISIBLE_TOASTS) {
        const oldest = container.firstElementChild;
        if (oldest) oldest.remove();
    }

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
    if (duration > 0 && status !== 'error') {
        const progress = document.createElement('div');
        progress.className = 'toast-progress';
        progress.style.animationDuration = `${duration}ms`;
        toast.appendChild(progress);
    }

    container.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    // Auto-close after duration (skip for errors so users can read details)
    if (duration > 0 && status !== 'error') {
        setTimeout(() => closeToast(toastId), duration);
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

// Function to Show the Response Modal (legacy support + new toast)
function showResponseModal(status, message, useToast = true) {
    if (useToast) {
        return showToast(status === 'failure' ? 'error' : status, message);
    }

    // Legacy modal code
    const modal = document.getElementById('responseModal');
    if (!modal) {
        return showToast(status === 'failure' ? 'error' : status, message);
    }

    const modalContent = document.getElementById('modalContent');
    const modalMessage = document.getElementById('modalMessage');

    // Remove any previous status classes
    modal.classList.remove('success', 'failure');

    // Add the correct class based on the status
    if (status === 'success') {
        modal.classList.add('success');
    } else {
        modal.classList.add('failure');
    }

    if (modalMessage) {
        modalMessage.textContent = message;
    }

    // Display Modal
    modal.style.display = 'block';

    // Auto-close modal (skip for failure so users can read error details)
    if (status === 'success') {
        setTimeout(() => closeResponseModal(), MODAL_AUTO_CLOSE_MS);
    }
}

// Function to Close the Modal
function closeResponseModal() {
    const modal = document.getElementById('responseModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Utility functions for different notification types
function showSuccess(message, duration) {
    return showToast('success', message, duration);
}

function showError(message, duration) {
    return showToast('error', message, duration);
}

function showWarning(message, duration) {
    return showToast('warning', message, duration);
}

function showInfo(message, duration) {
    return showToast('info', message, duration);
}

// Clear all toasts
function clearAllToasts() {
    if (toastContainer) {
        toastContainer.innerHTML = '';
    }
}

/**
 * Parse a fetch Response and surface a uniform modal for success/error.
 * Returns the parsed JSON object for further handling if needed.
 */
// Enhanced error handling with better user feedback
async function handleJsonResponse(response, options = {}) {
    const { showToastNotification = true, includeRequestId = false } = options;

    let data = null;
    try {
        data = await response.json();
    } catch (e) {
        // Non-JSON responses
        if (!response.ok) {
            console.warn('Non-JSON error response from', response.url, 'status:', response.status);
            const message = getErrorMessage(response.status);
            if (showToastNotification) {
                showToast('error', message);
            } else {
                showResponseModal('failure', message);
            }
        }
        return null;
    }

    if (!response.ok || (data && data.success === false) || data?.error) {
        const rid = includeRequestId && data?.request_id ? ` (id: ${data.request_id})` : '';
        const msg = (data && (data.error || data.message)) || getErrorMessage(response.status);
        const fullMessage = `${msg}${rid}`;

        if (showToastNotification) {
            showToast('error', fullMessage);
        } else {
            showResponseModal('failure', fullMessage);
        }
    } else {
        const rid = includeRequestId && data?.request_id ? ` (id: ${data.request_id})` : '';
        const msg = (data && data.message) || 'Operation completed successfully';
        const fullMessage = `${msg}${rid}`;

        if (showToastNotification) {
            showToast('success', fullMessage);
        } else {
            showResponseModal('success', fullMessage);
        }
    }
    return data;
}

function getErrorMessage(status, endpoint) {
    const ctx = endpoint ? ` (${endpoint})` : '';
    const errorMessages = {
        400: `Invalid request${ctx}. Please check your input.`,
        401: `Authentication required${ctx}. Please log in.`,
        403: `Access denied${ctx}. You don\'t have permission.`,
        404: `Resource not found${ctx}.`,
        408: `Request timed out${ctx}. Please try again.`,
        429: `Too many requests${ctx}. Please wait a moment and retry.`,
        500: `Server error${ctx}. Please try again later.`,
        502: `Service temporarily unavailable${ctx}. Retry in a few seconds.`,
        503: `Service unavailable${ctx}. Retry in a few seconds.`,
        504: `Gateway timeout${ctx}. Retry in a few seconds.`
    };

    return errorMessages[status] || `An unexpected error occurred${ctx}. Please try again.`;
}

// Wire up legacy modal close button (replaces inline onclick)
document.addEventListener('DOMContentLoaded', () => {
    const closeBtn = document.getElementById('responseModalClose');
    if (closeBtn) {
        closeBtn.addEventListener('click', closeResponseModal);
        closeBtn.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                closeResponseModal();
            }
        });
    }
});

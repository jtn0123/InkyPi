/**
 * Operation Status Indicators
 * Provides simple visual indicators for current operations and their success/failure states
 */

class OperationStatusManager {
    constructor() {
        this.currentOperations = new Map();
        this.recentOperations = [];
        this.maxRecentOperations = 10;
        this.statusContainer = null;

        this.initializeStatusDisplay();
    }

    /**
     * Initialize the status display container
     */
    initializeStatusDisplay() {
        // Create status container if it doesn't exist
        let container = document.getElementById('operationStatusContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'operationStatusContainer';
            container.className = 'operation-status-container';
            container.innerHTML = `
                <div class="status-header">
                    <span class="status-title">Operations</span>
                    <div class="status-summary">
                        <span id="activeOperationsCount" class="status-count">0 active</span>
                        <span id="recentSuccessRate" class="status-rate">—</span>
                    </div>
                </div>
                <div id="currentOperationsList" class="current-operations-list"></div>
                <div id="recentOperationsList" class="recent-operations-list" style="display: none;"></div>
                <button type="button" class="toggle-recent" id="toggleRecentBtn">
                    <span class="toggle-text">Show Recent</span>
                    <span class="toggle-icon">▼</span>
                </button>
            `;

            // Add to page (try to find a good spot)
            const targetContainer = document.querySelector('.status-bar') ||
                                  document.querySelector('.header') ||
                                  document.body;

            if (targetContainer) {
                targetContainer.appendChild(container);
            }

            const toggleBtn = container.querySelector('#toggleRecentBtn');
            if (toggleBtn) {
                toggleBtn.addEventListener('click', () => this.toggleRecentOperations());
            }
        }

        this.statusContainer = container;
        this.updateStatusDisplay();
    }

    /**
     * Start a new operation
     * @param {string} operationId - Unique ID for the operation
     * @param {string} description - Human-readable description
     * @param {Object} options - Additional options
     * @returns {Object} Operation object for updates
     */
    startOperation(operationId, description, options = {}) {
        const operation = {
            id: operationId,
            description,
            status: 'in_progress',
            startTime: Date.now(),
            endTime: null,
            duration: null,
            progress: 0,
            currentStep: null,
            error: null,
            metadata: options.metadata || {},
            ...options
        };

        this.currentOperations.set(operationId, operation);
        this.updateStatusDisplay();

        return {
            updateProgress: (progress, step) => this.updateOperationProgress(operationId, progress, step),
            updateStep: (step) => this.updateOperationStep(operationId, step),
            complete: (result) => this.completeOperation(operationId, true, result),
            fail: (error) => this.completeOperation(operationId, false, error),
            cancel: () => this.cancelOperation(operationId)
        };
    }

    /**
     * Update operation progress
     * @param {string} operationId - Operation ID
     * @param {number} progress - Progress percentage (0-100)
     * @param {string} step - Current step description
     */
    updateOperationProgress(operationId, progress, step = null) {
        const operation = this.currentOperations.get(operationId);
        if (!operation) return;

        operation.progress = Math.min(100, Math.max(0, progress));
        if (step) operation.currentStep = step;

        this.updateStatusDisplay();
    }

    /**
     * Update operation current step
     * @param {string} operationId - Operation ID
     * @param {string} step - Step description
     */
    updateOperationStep(operationId, step) {
        const operation = this.currentOperations.get(operationId);
        if (!operation) return;

        operation.currentStep = step;
        this.updateStatusDisplay();
    }

    /**
     * Complete an operation
     * @param {string} operationId - Operation ID
     * @param {boolean} success - Whether operation succeeded
     * @param {any} result - Result data or error message
     */
    completeOperation(operationId, success, result = null) {
        const operation = this.currentOperations.get(operationId);
        if (!operation) return;

        operation.status = success ? 'completed' : 'failed';
        operation.endTime = Date.now();
        operation.duration = operation.endTime - operation.startTime;
        operation.progress = success ? 100 : operation.progress;

        if (success) {
            operation.result = result;
        } else {
            operation.error = result;
        }

        // Move to recent operations
        this.recentOperations.unshift({...operation});
        if (this.recentOperations.length > this.maxRecentOperations) {
            this.recentOperations.pop();
        }

        // Remove from current operations
        this.currentOperations.delete(operationId);

        this.updateStatusDisplay();

        // Show brief success/failure notification
        this.showOperationNotification(operation);
    }

    /**
     * Cancel an operation
     * @param {string} operationId - Operation ID
     */
    cancelOperation(operationId) {
        const operation = this.currentOperations.get(operationId);
        if (!operation) return;

        operation.status = 'cancelled';
        operation.endTime = Date.now();
        operation.duration = operation.endTime - operation.startTime;

        // Move to recent operations
        this.recentOperations.unshift({...operation});
        if (this.recentOperations.length > this.maxRecentOperations) {
            this.recentOperations.pop();
        }

        this.currentOperations.delete(operationId);
        this.updateStatusDisplay();
    }

    /**
     * Update the status display
     */
    updateStatusDisplay() {
        if (!this.statusContainer) return;

        const activeCount = this.currentOperations.size;
        const successRate = this.calculateRecentSuccessRate();

        // Update counts
        const activeCountEl = document.getElementById('activeOperationsCount');
        if (activeCountEl) {
            activeCountEl.textContent = `${activeCount} active`;
        }

        const successRateEl = document.getElementById('recentSuccessRate');
        if (successRateEl) {
            successRateEl.textContent = successRate !== null ? `${successRate}% success` : '—';
        }

        // Update current operations list
        this.updateCurrentOperationsList();

        // Update recent operations list
        this.updateRecentOperationsList();

        // Show/hide the container based on activity
        if (activeCount > 0 || this.recentOperations.length > 0) {
            this.statusContainer.style.display = 'block';
        } else {
            this.statusContainer.style.display = 'none';
        }
    }

    /**
     * Update current operations list
     */
    updateCurrentOperationsList() {
        const listEl = document.getElementById('currentOperationsList');
        if (!listEl) return;

        if (this.currentOperations.size === 0) {
            listEl.textContent = '';
            const noOps = document.createElement('div');
            noOps.className = 'no-operations';
            noOps.textContent = 'No active operations';
            listEl.appendChild(noOps);
            return;
        }

        listEl.textContent = '';
        Array.from(this.currentOperations.values()).forEach(op => {
            listEl.appendChild(this.renderOperationItem(op, true));
        });
    }

    /**
     * Update recent operations list
     */
    updateRecentOperationsList() {
        const listEl = document.getElementById('recentOperationsList');
        if (!listEl) return;

        if (this.recentOperations.length === 0) {
            listEl.textContent = '';
            const noOps = document.createElement('div');
            noOps.className = 'no-operations';
            noOps.textContent = 'No recent operations';
            listEl.appendChild(noOps);
            return;
        }

        listEl.textContent = '';
        this.recentOperations.forEach(op => {
            listEl.appendChild(this.renderOperationItem(op, false));
        });
    }

    /**
     * Render an operation item
     * @param {Object} operation - Operation data
     * @param {boolean} isCurrent - Whether this is a current operation
     * @returns {HTMLElement} DOM element for the operation
     */
    renderOperationItem(operation, isCurrent) {
        const statusIcon = {
            in_progress: '⟳',
            completed: '✓',
            failed: '✕',
            cancelled: '○'
        }[operation.status] || '?';

        const statusClass = `status-${operation.status}`;
        const duration = operation.duration ? this.formatDuration(operation.duration) : '';
        const elapsed = isCurrent ? this.formatDuration(Date.now() - operation.startTime) : '';

        const item = document.createElement('div');
        item.className = `operation-item ${statusClass}`;

        const header = document.createElement('div');
        header.className = 'operation-header';
        const iconSpan = document.createElement('span');
        iconSpan.className = 'operation-icon';
        iconSpan.textContent = statusIcon;
        const descSpan = document.createElement('span');
        descSpan.className = 'operation-description';
        descSpan.textContent = operation.description;
        const timeSpan = document.createElement('span');
        timeSpan.className = 'operation-time';
        timeSpan.textContent = duration || elapsed;
        header.appendChild(iconSpan);
        header.appendChild(descSpan);
        header.appendChild(timeSpan);
        item.appendChild(header);

        if (isCurrent && operation.progress > 0) {
            const progressDiv = document.createElement('div');
            progressDiv.className = 'operation-progress';
            const bar = document.createElement('div');
            bar.className = 'progress-bar';
            const fill = document.createElement('div');
            fill.className = 'progress-fill';
            fill.style.width = `${operation.progress}%`;
            bar.appendChild(fill);
            const pctSpan = document.createElement('span');
            pctSpan.className = 'progress-text';
            pctSpan.textContent = `${operation.progress}%`;
            progressDiv.appendChild(bar);
            progressDiv.appendChild(pctSpan);
            item.appendChild(progressDiv);
        }

        if (operation.currentStep) {
            const stepDiv = document.createElement('div');
            stepDiv.className = 'operation-step';
            stepDiv.textContent = operation.currentStep;
            item.appendChild(stepDiv);
        }

        if (operation.error) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'operation-error';
            errorDiv.textContent = operation.error;
            item.appendChild(errorDiv);
        }

        return item;
    }

    /**
     * Calculate recent success rate
     * @returns {number|null} Success rate percentage or null if no recent operations
     */
    calculateRecentSuccessRate() {
        if (this.recentOperations.length === 0) return null;

        const recent = this.recentOperations.slice(0, 5); // Last 5 operations
        const successful = recent.filter(op => op.status === 'completed').length;

        return Math.round((successful / recent.length) * 100);
    }

    /**
     * Toggle recent operations visibility
     */
    toggleRecentOperations() {
        const listEl = document.getElementById('recentOperationsList');
        const toggleBtn = this.statusContainer?.querySelector('.toggle-recent');

        if (!listEl || !toggleBtn) return;

        const isVisible = listEl.style.display !== 'none';
        listEl.style.display = isVisible ? 'none' : 'block';

        const textEl = toggleBtn.querySelector('.toggle-text');
        const iconEl = toggleBtn.querySelector('.toggle-icon');

        if (textEl) textEl.textContent = isVisible ? 'Show Recent' : 'Hide Recent';
        if (iconEl) iconEl.textContent = isVisible ? '▼' : '▲';
    }

    /**
     * Show a brief notification for completed operations
     * @param {Object} operation - Completed operation
     */
    showOperationNotification(operation) {
        // Use existing toast system if available
        if (window.showToast) {
            const status = operation.status === 'completed' ? 'success' : 'error';
            const message = operation.status === 'completed'
                ? `${operation.description} completed (${this.formatDuration(operation.duration)})`
                : `${operation.description} failed: ${operation.error}`;

            window.showToast(status, message, 3000);
        }
    }

    /**
     * Format duration in human-readable format
     * @param {number} ms - Duration in milliseconds
     * @returns {string} Formatted duration
     */
    formatDuration(ms) {
        const seconds = Math.floor(ms / 1000);
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;

        if (minutes > 0) {
            return `${minutes}m ${remainingSeconds}s`;
        }
        return `${seconds}s`;
    }

    /**
     * Get current operation status
     * @param {string} operationId - Operation ID
     * @returns {Object|null} Operation status or null
     */
    getOperationStatus(operationId) {
        return this.currentOperations.get(operationId) || null;
    }

    /**
     * Get summary of all operations
     * @returns {Object} Operations summary
     */
    getOperationsSummary() {
        return {
            active: this.currentOperations.size,
            recent: this.recentOperations.length,
            successRate: this.calculateRecentSuccessRate(),
            currentOperations: Array.from(this.currentOperations.values()),
            recentOperations: this.recentOperations.slice(0, 5)
        };
    }

    /**
     * Clear all recent operations
     */
    clearRecentOperations() {
        this.recentOperations = [];
        this.updateStatusDisplay();
    }
}

// Create global instance
window.OperationStatusManager = OperationStatusManager;
window.operationStatus = new OperationStatusManager();

// Helper function to start an operation
window.startOperation = function(id, description, options = {}) {
    return window.operationStatus.startOperation(id, description, options);
};

// Integration with existing progress systems
document.addEventListener('DOMContentLoaded', () => {
    // Auto-detect when form submissions start
    document.addEventListener('submit', (e) => {
        const form = e.target;
        const formId = form.id || 'form-' + Date.now();
        const description = form.getAttribute('aria-label') || 'Form submission';

        // Start operation tracking
        const operation = window.operationStatus.startOperation(formId, description);

        // Per-operation closure state — not shared across concurrent submissions
        let operationCompleted = false;
        let localTimeoutId = null;
        const previousFetch = window.fetch;

        function finishOperation() {
            if (localTimeoutId) {
                clearTimeout(localTimeoutId);
                localTimeoutId = null;
            }
            // Restore the fetch that was in place when this operation started,
            // but only if our wrapper is still the active one.
            if (window.fetch === wrappedFetch) {
                window.fetch = previousFetch;
            }
        }

        function wrappedFetch(...args) {
            return previousFetch(...args).then(response => {
                if (!operationCompleted) {
                    operationCompleted = true;
                    finishOperation();
                    if (response.ok) {
                        operation.complete('Form submitted successfully');
                    } else {
                        operation.fail(`Request failed: ${response.status} ${response.statusText}`);
                    }
                }
                return response;
            }).catch(error => {
                if (!operationCompleted) {
                    operationCompleted = true;
                    finishOperation();
                    operation.fail(`Network error: ${error.message}`);
                }
                throw error;
            });
        }

        // Install this operation's wrapper on top of whatever fetch is current
        window.fetch = wrappedFetch;

        // Fail the operation if no fetch response arrives within the timeout
        localTimeoutId = setTimeout(() => {
            if (!operationCompleted) {
                operationCompleted = true;
                finishOperation();
                operation.fail('Request timeout');
            }
        }, 30000);
    });
});
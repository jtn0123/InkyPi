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
                <button type="button" class="toggle-recent" onclick="operationStatus.toggleRecentOperations()">
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
            listEl.innerHTML = '<div class="no-operations">No active operations</div>';
            return;
        }

        const operationsHtml = Array.from(this.currentOperations.values())
            .map(op => this.renderOperationItem(op, true))
            .join('');

        listEl.innerHTML = operationsHtml;
    }

    /**
     * Update recent operations list
     */
    updateRecentOperationsList() {
        const listEl = document.getElementById('recentOperationsList');
        if (!listEl) return;

        if (this.recentOperations.length === 0) {
            listEl.innerHTML = '<div class="no-operations">No recent operations</div>';
            return;
        }

        const operationsHtml = this.recentOperations
            .map(op => this.renderOperationItem(op, false))
            .join('');

        listEl.innerHTML = operationsHtml;
    }

    /**
     * Render an operation item
     * @param {Object} operation - Operation data
     * @param {boolean} isCurrent - Whether this is a current operation
     * @returns {string} HTML string
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

        return `
            <div class="operation-item ${statusClass}">
                <div class="operation-header">
                    <span class="operation-icon">${statusIcon}</span>
                    <span class="operation-description">${operation.description}</span>
                    <span class="operation-time">${duration || elapsed}</span>
                </div>
                ${isCurrent && operation.progress > 0 ? `
                    <div class="operation-progress">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${operation.progress}%"></div>
                        </div>
                        <span class="progress-text">${operation.progress}%</span>
                    </div>
                ` : ''}
                ${operation.currentStep ? `
                    <div class="operation-step">${operation.currentStep}</div>
                ` : ''}
                ${operation.error ? `
                    <div class="operation-error">${operation.error}</div>
                ` : ''}
            </div>
        `;
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

        // Try to detect when the form submission completes
        const originalFetch = window.fetch;
        let operationCompleted = false;

        // Wrap fetch to detect completion
        window.fetch = function(...args) {
            return originalFetch.apply(this, args).then(response => {
                if (!operationCompleted) {
                    if (response.ok) {
                        operation.complete('Form submitted successfully');
                    } else {
                        operation.fail(`Request failed: ${response.status} ${response.statusText}`);
                    }
                    operationCompleted = true;
                }
                return response;
            }).catch(error => {
                if (!operationCompleted) {
                    operation.fail(`Network error: ${error.message}`);
                    operationCompleted = true;
                }
                throw error;
            });
        };

        // Restore original fetch after a timeout
        setTimeout(() => {
            window.fetch = originalFetch;
            if (!operationCompleted) {
                operation.fail('Request timeout');
            }
        }, 30000);
    });
});
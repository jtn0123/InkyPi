/**
 * RefreshSettingsManager - Unified handler for refresh settings across the application
 * Handles: modal display, prepopulation, form submission, and validation
 */
class RefreshSettingsManager {
    /**
     * @param {string} modalId - ID of the modal element
     * @param {string} prefix - Prefix for form field IDs (e.g., 'add', 'edit', 'modal')
     */
    constructor(modalId, prefix) {
        this.modalId = modalId;
        this.prefix = prefix;
        this.currentData = null; // Store current plugin data for submission

        // Cache DOM elements
        this.modal = null;
        this.radioInterval = null;
        this.radioScheduled = null;
        this.inputInterval = null;
        this.inputScheduled = null;
        this.selectUnit = null;
        this.groupInterval = null;
        this.groupScheduled = null;

        this.initialized = false;
    }

    /**
     * Initialize the manager - must be called after DOM is loaded
     */
    init() {
        if (this.initialized) return;

        this.modal = document.getElementById(this.modalId);
        if (!this.modal) {
            console.error(`RefreshSettingsManager: Modal '${this.modalId}' not found`);
            return;
        }

        // Cache form elements
        this.radioInterval = document.getElementById(`${this.prefix}-refresh-interval`);
        this.radioScheduled = document.getElementById(`${this.prefix}-refresh-scheduled`);
        this.inputInterval = document.getElementById(`${this.prefix}-interval`);
        this.inputScheduled = document.getElementById(`${this.prefix}-scheduled`);
        this.selectUnit = document.getElementById(`${this.prefix}-unit`);
        this.groupInterval = document.getElementById(`${this.prefix}-group-interval`);
        this.groupScheduled = document.getElementById(`${this.prefix}-group-scheduled`);

        if (!this.radioInterval || !this.radioScheduled) {
            console.error(`RefreshSettingsManager: Form elements with prefix '${this.prefix}' not found`);
            return;
        }

        this.setupInteractiveHandlers();
        this.initialized = true;
    }

    /**
     * Set up interactive click handlers for radio groups
     */
    setupInteractiveHandlers() {
        const activateGroup = (radio, input) => {
            radio.checked = true;
            this.syncScheduledDefaults();
            setTimeout(() => input.focus(), 0);
        };

        // Click anywhere in interval group → activate interval
        if (this.groupInterval) {
            this.groupInterval.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
                activateGroup(this.radioInterval, this.inputInterval);
            });
        }

        // Click anywhere in scheduled group → activate scheduled
        if (this.groupScheduled) {
            this.groupScheduled.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
                activateGroup(this.radioScheduled, this.inputScheduled);
            });
        }

        // Clicking radio buttons → focus inputs
        this.radioInterval.addEventListener('click', () => activateGroup(this.radioInterval, this.inputInterval));
        this.radioScheduled.addEventListener('click', () => activateGroup(this.radioScheduled, this.inputScheduled));

        // Focusing inputs → auto-select their radio
        this.inputInterval.addEventListener('focus', () => {
            this.radioInterval.checked = true;
            this.syncScheduledDefaults();
        });
        this.inputScheduled.addEventListener('focus', () => {
            this.radioScheduled.checked = true;
            this.syncScheduledDefaults();
        });
        if (this.selectUnit) {
            this.selectUnit.addEventListener('focus', () => {
                this.radioInterval.checked = true;
                this.syncScheduledDefaults();
            });
        }
    }

    /**
     * Apply defaults and show/hide help text based on current radio selection.
     * Option A: prefill 09:00 when switching to Daily at with no value.
     * Option B: show inline guidance text when Daily at is active.
     */
    syncScheduledDefaults() {
        const scheduledActive = this.radioScheduled && this.radioScheduled.checked;

        // Option A: default time
        if (scheduledActive && this.inputScheduled && !this.inputScheduled.value) {
            this.inputScheduled.value = '09:00';
        }

        // Option B: inline help text
        const helpEl = this.modal
            ? this.modal.querySelector(`#${this.prefix}-scheduled-help`)
            : null;
        if (helpEl) {
            helpEl.style.display = scheduledActive ? 'block' : 'none';
        }
    }

    /**
     * Convert seconds to appropriate unit and value
     * @param {number} seconds - Seconds to convert
     * @returns {{value: number, unit: string}}
     */
    secondsToUnit(seconds) {
        if (seconds % 86400 === 0) {
            return { value: seconds / 86400, unit: 'day' };
        }
        if (seconds % 3600 === 0) {
            return { value: seconds / 3600, unit: 'hour' };
        }
        if (seconds % 60 === 0) {
            return { value: seconds / 60, unit: 'minute' };
        }
        // Default to minutes if not evenly divisible
        return { value: Math.round(seconds / 60), unit: 'minute' };
    }

    /**
     * Prepopulate form with existing refresh settings
     * @param {Object} refreshSettings - Refresh settings object {interval: number} or {scheduled: string}
     */
    prepopulate(refreshSettings) {
        if (!refreshSettings) return;

        if (refreshSettings.interval) {
            const { value, unit } = this.secondsToUnit(refreshSettings.interval);
            this.radioInterval.checked = true;
            this.inputInterval.value = value;
            this.selectUnit.value = unit;
        } else if (refreshSettings.scheduled) {
            this.radioScheduled.checked = true;
            this.inputScheduled.value = refreshSettings.scheduled;
        }
    }

    /**
     * Get current form values as an object
     * @returns {{refreshType: string, interval?: string, unit?: string, refreshTime?: string}}
     */
    getFormData() {
        const refreshType = this.modal.querySelector(`input[name="refreshType"]:checked`)?.value;
        const data = { refreshType };

        if (refreshType === 'interval') {
            data.interval = this.inputInterval.value;
            data.unit = this.selectUnit.value;
        } else if (refreshType === 'scheduled') {
            data.refreshTime = this.inputScheduled.value;
        }

        return data;
    }

    /**
     * Validate form data
     * @param {Object} data - Form data to validate
     * @returns {{valid: boolean, error?: string}}
     */
    validate(data) {
        if (!data.refreshType) {
            return { valid: false, error: 'Please select a refresh type' };
        }

        if (data.refreshType === 'interval') {
            if (!data.interval || !/^\d+$/.test(data.interval)) {
                return { valid: false, error: 'Refresh interval must be at least 1' };
            }
            const interval = Number(data.interval);
            if (interval < 1) {
                return { valid: false, error: 'Refresh interval must be at least 1' };
            }
            if (interval > 999) {
                return { valid: false, error: 'Refresh interval must be between 1 and 999' };
            }
            if (!data.unit || !['minute', 'hour', 'day'].includes(data.unit)) {
                return { valid: false, error: 'Please select a valid time unit (minute, hour, or day)' };
            }
        } else if (data.refreshType === 'scheduled') {
            if (!data.refreshTime) {
                return { valid: false, error: 'Please select a refresh time' };
            }
            if (!/^\d{2}:\d{2}(:\d{2})?$/.test(data.refreshTime)) {
                return { valid: false, error: 'Refresh time must be in HH:MM format' };
            }
            const [hoursStr, minutesStr, secondsStr = '00'] = data.refreshTime.split(':');
            const hours = Number(hoursStr);
            const minutes = Number(minutesStr);
            const seconds = Number(secondsStr);
            if (
                hours < 0 || hours > 23 ||
                minutes < 0 || minutes > 59 ||
                seconds < 0 || seconds > 59
            ) {
                return { valid: false, error: 'Refresh time must be in HH:MM format' };
            }
        }

        return { valid: true };
    }

    /**
     * Open modal with optional prepopulated data
     * @param {Object} data - Optional data for prepopulation
     */
    open(data = null) {
        if (!this.initialized) {
            console.error('RefreshSettingsManager: Not initialized. Call init() first.');
            return;
        }

        this.currentData = data;

        // Prepopulate if data provided
        if (data && data.refreshSettings) {
            this.prepopulate(data.refreshSettings);
        }

        this.modal.style.display = 'block';
    }

    /**
     * Close the modal
     */
    close() {
        if (this.modal) {
            this.modal.style.display = 'none';
        }
    }

    /**
     * Submit the form
     * @param {Function} submitHandler - Async function to handle submission
     *                                   Will be called with (formData, currentData)
     * @returns {Promise<void>}
     */
    async submit(submitHandler) {
        const formData = this.getFormData();
        const validation = this.validate(formData);

        if (!validation.valid) {
            if (window.showResponseModal) {
                showResponseModal('failure', `Error! ${validation.error}`);
            } else {
                alert(validation.error);
            }
            return;
        }

        try {
            await submitHandler(formData, this.currentData);
            this.close();
        } catch (error) {
            console.error('RefreshSettingsManager: Submit error:', error);
            if (window.showResponseModal) {
                showResponseModal('failure', `Error! ${error.message}`);
            } else {
                alert(`Error: ${error.message}`);
            }
        }
    }
}

// Global utility function to create and initialize a manager
function createRefreshSettingsManager(modalId, prefix) {
    const manager = new RefreshSettingsManager(modalId, prefix);
    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => manager.init());
    } else {
        manager.init();
    }
    return manager;
}

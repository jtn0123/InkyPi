/**
 * Enhanced Progress Display System
 * Provides detailed step-by-step progress tracking with timing information
 */

class EnhancedProgressDisplay {
    constructor(progressElement, options = {}) {
        this.progressElement = progressElement;
        this.options = {
            showTimings: true,
            showSubsteps: true,
            animateProgress: true,
            autoScroll: true,
            ...options
        };

        this.currentSteps = [];
        this.startTime = null;
        this.currentStepIndex = -1;
        this.stepTimings = new Map();

        this.initializeElements();
    }

    initializeElements() {
        if (!this.progressElement) return;

        // Create enhanced progress structure
        this.progressElement.innerHTML = `
            <div class="enhanced-progress-header">
                <div class="progress-title-section">
                    <span id="enhancedProgressText" class="progress-title">Preparing...</span>
                    <span id="enhancedProgressSubtext" class="progress-subtitle"></span>
                </div>
                <div class="progress-controls">
                    <span id="enhancedProgressElapsed" class="progress-elapsed">0s</span>
                    <button type="button" class="progress-close" aria-label="Close progress" onclick="this.closest('.progress-block').style.display='none'">×</button>
                </div>
            </div>
            <div class="enhanced-progress-bar-section">
                <div class="progress-bar-container">
                    <div id="enhancedProgressBar" class="enhanced-progress-fill" style="width: 0%"></div>
                </div>
                <div class="progress-percentage">
                    <span id="enhancedProgressPercent">0%</span>
                </div>
            </div>
            <div class="enhanced-progress-steps" id="enhancedProgressSteps">
                <!-- Steps will be added dynamically -->
            </div>
            <div class="enhanced-progress-details" id="enhancedProgressDetails" style="display: none;">
                <div class="progress-details-header">
                    <span>Step Details</span>
                    <button type="button" class="details-toggle" onclick="this.closest('.enhanced-progress-details').style.display='none'">Hide</button>
                </div>
                <ol id="enhancedProgressLog" class="enhanced-progress-log" aria-live="polite"></ol>
            </div>
        `;

        // Get element references
        this.elements = {
            text: this.progressElement.querySelector('#enhancedProgressText'),
            subtext: this.progressElement.querySelector('#enhancedProgressSubtext'),
            elapsed: this.progressElement.querySelector('#enhancedProgressElapsed'),
            bar: this.progressElement.querySelector('#enhancedProgressBar'),
            percent: this.progressElement.querySelector('#enhancedProgressPercent'),
            steps: this.progressElement.querySelector('#enhancedProgressSteps'),
            details: this.progressElement.querySelector('#enhancedProgressDetails'),
            log: this.progressElement.querySelector('#enhancedProgressLog')
        };
    }

    /**
     * Start a new progress operation with defined steps
     * @param {Array<string>} steps - Array of step names
     * @param {string} title - Main operation title
     */
    start(steps = [], title = 'Processing...') {
        this.currentSteps = steps;
        this.startTime = Date.now();
        this.currentStepIndex = -1;
        this.stepTimings.clear();

        if (this.elements.text) {
            this.elements.text.textContent = title;
        }
        if (this.elements.subtext) {
            this.elements.subtext.textContent = '';
        }

        this.updateProgress(0);
        this.renderSteps();
        this.startElapsedTimer();

        this.progressElement.style.display = 'block';

        // Add initial log entry
        this.addLogEntry('Operation started', 'info');
    }

    /**
     * Move to the next step with optional description
     * @param {string} description - Step description
     * @param {Array<string>} substeps - Optional substeps for this step
     */
    nextStep(description = '', substeps = []) {
        this.currentStepIndex++;
        const stepName = this.currentSteps[this.currentStepIndex] || `Step ${this.currentStepIndex + 1}`;

        // Record timing for previous step
        if (this.currentStepIndex > 0) {
            const prevStepTime = Date.now() - this.startTime;
            this.stepTimings.set(this.currentStepIndex - 1, prevStepTime);
        }

        const progress = this.currentSteps.length > 0
            ? ((this.currentStepIndex + 1) / this.currentSteps.length) * 100
            : (this.currentStepIndex + 1) * 20; // Default to 20% increments

        this.updateStep(stepName, description, Math.min(progress, 100), substeps);
        this.updateStepVisual(this.currentStepIndex);

        // Add log entry
        this.addLogEntry(`${stepName}${description ? ': ' + description : ''}`, 'step');
    }

    /**
     * Update the current step with new information
     * @param {string} stepName - Step name
     * @param {string} description - Step description
     * @param {number} progress - Progress percentage (0-100)
     * @param {Array<string>} substeps - Optional substeps
     */
    updateStep(stepName, description = '', progress = 0, substeps = []) {
        if (this.elements.text) {
            this.elements.text.textContent = stepName;
        }
        if (this.elements.subtext) {
            this.elements.subtext.textContent = description;
        }

        this.updateProgress(progress);

        // Show substeps if provided
        if (substeps.length > 0 && this.options.showSubsteps) {
            this.showSubsteps(substeps);
        }
    }

    /**
     * Update progress bar and percentage
     * @param {number} progress - Progress percentage (0-100)
     */
    updateProgress(progress) {
        const clampedProgress = Math.min(100, Math.max(0, progress));

        if (this.elements.bar) {
            if (this.options.animateProgress) {
                this.elements.bar.style.transition = 'width 0.3s ease';
            }
            this.elements.bar.style.width = `${clampedProgress}%`;
        }

        if (this.elements.percent) {
            this.elements.percent.textContent = `${Math.round(clampedProgress)}%`;
        }
    }

    /**
     * Complete the current operation
     * @param {string} message - Completion message
     * @param {boolean} success - Whether operation was successful
     */
    complete(message = 'Operation completed', success = true) {
        // Record final timing
        if (this.currentStepIndex >= 0) {
            const finalTime = Date.now() - this.startTime;
            this.stepTimings.set(this.currentStepIndex, finalTime);
        }

        this.updateProgress(100);

        if (this.elements.text) {
            this.elements.text.textContent = message;
        }
        if (this.elements.subtext) {
            const totalTime = this.formatElapsed(Date.now() - this.startTime);
            this.elements.subtext.textContent = `Completed in ${totalTime}`;
        }

        // Update all steps to completed
        const stepElements = this.elements.steps?.querySelectorAll('.enhanced-step');
        stepElements?.forEach(step => {
            step.classList.add('completed');
            step.classList.remove('active', 'failed');
        });

        // Add completion log entry
        this.addLogEntry(message, success ? 'success' : 'error');

        // Auto-hide after delay
        setTimeout(() => {
            if (this.progressElement) {
                this.progressElement.style.display = 'none';
            }
        }, 3000);

        this.stopElapsedTimer();
    }

    /**
     * Mark current operation as failed
     * @param {string} error - Error message
     */
    fail(error = 'Operation failed') {
        if (this.elements.text) {
            this.elements.text.textContent = 'Operation Failed';
        }
        if (this.elements.subtext) {
            this.elements.subtext.textContent = error;
        }

        // Mark current step as failed
        if (this.currentStepIndex >= 0) {
            const stepElements = this.elements.steps?.querySelectorAll('.enhanced-step');
            const currentStep = stepElements?.[this.currentStepIndex];
            if (currentStep) {
                currentStep.classList.add('failed');
                currentStep.classList.remove('active');
            }
        }

        // Add error log entry
        this.addLogEntry(`Error: ${error}`, 'error');

        this.stopElapsedTimer();
    }

    /**
     * Render the step indicators
     */
    renderSteps() {
        if (!this.elements.steps || this.currentSteps.length === 0) return;

        this.elements.steps.innerHTML = this.currentSteps.map((step, index) => `
            <div class="enhanced-step" data-step-index="${index}">
                <div class="step-indicator">
                    <div class="step-number">${index + 1}</div>
                </div>
                <div class="step-content">
                    <div class="step-name">${step}</div>
                    <div class="step-timing" style="display: none;"></div>
                </div>
            </div>
        `).join('');
    }

    /**
     * Update visual state of a specific step
     * @param {number} stepIndex - Index of step to update
     */
    updateStepVisual(stepIndex) {
        const stepElements = this.elements.steps?.querySelectorAll('.enhanced-step');
        if (!stepElements) return;

        stepElements.forEach((element, index) => {
            const indicator = element.querySelector('.step-indicator');
            const timing = element.querySelector('.step-timing');

            if (index < stepIndex) {
                // Completed step
                element.classList.add('completed');
                element.classList.remove('active', 'failed');

                // Show timing if available
                if (this.stepTimings.has(index) && timing && this.options.showTimings) {
                    const elapsed = this.stepTimings.get(index);
                    timing.textContent = this.formatElapsed(elapsed - (index > 0 ? this.stepTimings.get(index - 1) || 0 : 0));
                    timing.style.display = 'block';
                }
            } else if (index === stepIndex) {
                // Current step
                element.classList.add('active');
                element.classList.remove('completed', 'failed');
            } else {
                // Future step
                element.classList.remove('active', 'completed', 'failed');
            }
        });
    }

    /**
     * Show substeps for current operation
     * @param {Array<string>} substeps - Array of substep descriptions
     */
    showSubsteps(substeps) {
        // Implementation for showing substeps in the current step
        // This could be expanded to show a detailed breakdown
    }

    /**
     * Add an entry to the detailed log
     * @param {string} message - Log message
     * @param {string} type - Log type (info, step, success, error)
     */
    addLogEntry(message, type = 'info') {
        if (!this.elements.log) return;

        const li = document.createElement('li');
        li.className = `log-entry log-${type}`;

        const timestamp = document.createElement('time');
        timestamp.textContent = new Date().toLocaleTimeString();
        timestamp.className = 'log-time';

        const content = document.createElement('span');
        content.textContent = message;
        content.className = 'log-content';

        li.appendChild(timestamp);
        li.appendChild(content);
        this.elements.log.appendChild(li);

        // Auto-scroll to bottom
        if (this.options.autoScroll) {
            try {
                this.elements.log.scrollTop = this.elements.log.scrollHeight;
            } catch (e) {}
        }
    }

    /**
     * Show/hide detailed progress information
     * @param {boolean} show - Whether to show details
     */
    toggleDetails(show = null) {
        if (!this.elements.details) return;

        const isVisible = this.elements.details.style.display !== 'none';
        const shouldShow = show !== null ? show : !isVisible;

        this.elements.details.style.display = shouldShow ? 'block' : 'none';
    }

    /**
     * Start the elapsed time timer
     */
    startElapsedTimer() {
        this.stopElapsedTimer(); // Clear any existing timer

        this.elapsedTimer = setInterval(() => {
            if (this.elements.elapsed && this.startTime) {
                const elapsed = Date.now() - this.startTime;
                this.elements.elapsed.textContent = this.formatElapsed(elapsed);
            }
        }, 1000);
    }

    /**
     * Stop the elapsed time timer
     */
    stopElapsedTimer() {
        if (this.elapsedTimer) {
            clearInterval(this.elapsedTimer);
            this.elapsedTimer = null;
        }
    }

    /**
     * Format elapsed time in a human-readable format
     * @param {number} ms - Milliseconds
     * @returns {string} Formatted time string
     */
    formatElapsed(ms) {
        const seconds = Math.floor(ms / 1000);
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;

        if (minutes > 0) {
            return `${minutes}m ${remainingSeconds}s`;
        }
        return `${seconds}s`;
    }

    /**
     * Get timing summary for completed operation
     * @returns {Object} Timing summary
     */
    getTimingSummary() {
        const summary = {
            totalTime: this.startTime ? Date.now() - this.startTime : 0,
            stepTimings: {},
            steps: this.currentSteps
        };

        this.stepTimings.forEach((time, index) => {
            const stepName = this.currentSteps[index] || `Step ${index + 1}`;
            const prevTime = index > 0 ? this.stepTimings.get(index - 1) || 0 : 0;
            summary.stepTimings[stepName] = time - prevTime;
        });

        return summary;
    }
}

// Create global instance for easy access
window.EnhancedProgressDisplay = EnhancedProgressDisplay;

// Helper function to create and manage enhanced progress
window.createEnhancedProgress = function(containerId, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.warn(`Progress container with ID '${containerId}' not found`);
        return null;
    }

    return new EnhancedProgressDisplay(container, options);
};
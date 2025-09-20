/**
 * API Endpoint Validation Utility
 * Provides basic connectivity testing for API endpoints in plugin settings
 */

class APIValidator {
    constructor() {
        this.validationCache = new Map();
        this.activeValidations = new Map();
        this.cacheExpiry = 5 * 60 * 1000; // 5 minutes
    }

    /**
     * Validate an API endpoint
     * @param {string} url - API endpoint URL
     * @param {Object} options - Validation options
     * @returns {Promise<Object>} Validation result
     */
    async validateEndpoint(url, options = {}) {
        const {
            timeout = 5000,
            method = 'GET',
            headers = {},
            useCache = true,
            retries = 1
        } = options;

        // Check cache first
        if (useCache && this.validationCache.has(url)) {
            const cached = this.validationCache.get(url);
            if (Date.now() - cached.timestamp < this.cacheExpiry) {
                return cached.result;
            }
        }

        // Check if validation is already in progress
        if (this.activeValidations.has(url)) {
            return await this.activeValidations.get(url);
        }

        // Start new validation
        const validationPromise = this._performValidation(url, {
            timeout,
            method,
            headers,
            retries
        });

        this.activeValidations.set(url, validationPromise);

        try {
            const result = await validationPromise;

            // Cache the result
            if (useCache) {
                this.validationCache.set(url, {
                    result,
                    timestamp: Date.now()
                });
            }

            return result;
        } finally {
            this.activeValidations.delete(url);
        }
    }

    /**
     * Perform the actual validation
     * @private
     */
    async _performValidation(url, options) {
        const startTime = Date.now();
        let lastError = null;

        for (let attempt = 0; attempt <= options.retries; attempt++) {
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), options.timeout);

                const response = await fetch(url, {
                    method: options.method,
                    headers: {
                        ...options.headers,
                        'User-Agent': 'InkyPi-Validator/1.0'
                    },
                    signal: controller.signal,
                    mode: 'cors',
                    cache: 'no-cache'
                });

                clearTimeout(timeoutId);
                const responseTime = Date.now() - startTime;

                return {
                    success: true,
                    status: response.status,
                    statusText: response.statusText,
                    responseTime,
                    reachable: true,
                    error: null,
                    attempt: attempt + 1
                };

            } catch (error) {
                lastError = error;

                // Don't retry on certain errors
                if (error.name === 'AbortError') {
                    break; // Timeout
                }
                if (error.message.includes('CORS')) {
                    break; // CORS errors won't be fixed by retrying
                }

                // Wait before retry
                if (attempt < options.retries) {
                    await new Promise(resolve => setTimeout(resolve, 1000));
                }
            }
        }

        const responseTime = Date.now() - startTime;

        return {
            success: false,
            status: null,
            statusText: null,
            responseTime,
            reachable: false,
            error: this._categorizeError(lastError),
            attempt: options.retries + 1
        };
    }

    /**
     * Categorize errors for better user feedback
     * @private
     */
    _categorizeError(error) {
        if (!error) return 'Unknown error';

        if (error.name === 'AbortError') {
            return 'Request timeout - endpoint may be slow or unreachable';
        }
        if (error.message.includes('CORS')) {
            return 'CORS policy restriction - endpoint exists but blocks browser requests';
        }
        if (error.message.includes('NetworkError')) {
            return 'Network error - check internet connection';
        }
        if (error.message.includes('Failed to fetch')) {
            return 'Cannot reach endpoint - may be offline or blocked';
        }

        return error.message || 'Connection failed';
    }

    /**
     * Validate multiple endpoints concurrently
     * @param {Array<Object>} endpoints - Array of {url, options} objects
     * @returns {Promise<Array<Object>>} Array of validation results
     */
    async validateMultiple(endpoints) {
        const validations = endpoints.map(({url, options}) =>
            this.validateEndpoint(url, options).catch(error => ({
                success: false,
                error: error.message,
                url
            }))
        );

        return await Promise.all(validations);
    }

    /**
     * Clear validation cache
     */
    clearCache() {
        this.validationCache.clear();
    }

    /**
     * Get cached result if available
     * @param {string} url - API endpoint URL
     * @returns {Object|null} Cached result or null
     */
    getCachedResult(url) {
        if (this.validationCache.has(url)) {
            const cached = this.validationCache.get(url);
            if (Date.now() - cached.timestamp < this.cacheExpiry) {
                return cached.result;
            }
        }
        return null;
    }
}

/**
 * API Validation UI Helper
 * Provides UI components for showing validation status
 */
class APIValidationUI {
    constructor(validator = null) {
        this.validator = validator || new APIValidator();
        this.indicators = new Map();
    }

    /**
     * Create a validation indicator for an input field
     * @param {HTMLInputElement} input - Input element
     * @param {Object} options - Validation options
     * @returns {HTMLElement} Indicator element
     */
    createValidationIndicator(input, options = {}) {
        const {
            position = 'after',
            showDetails = true,
            validateOnChange = true,
            debounceMs = 1000
        } = options;

        // Create indicator element
        const indicator = document.createElement('div');
        indicator.className = 'api-validation-indicator';
        indicator.innerHTML = `
            <div class="validation-status" role="status" aria-live="polite">
                <span class="status-icon"></span>
                <span class="status-text">Not validated</span>
            </div>
            ${showDetails ? '<div class="validation-details" style="display: none;"></div>' : ''}
        `;

        // Position the indicator
        if (position === 'after') {
            input.parentNode.insertBefore(indicator, input.nextSibling);
        } else {
            input.parentNode.insertBefore(indicator, input);
        }

        // Set up validation on input change
        if (validateOnChange) {
            let debounceTimer;
            const debouncedValidate = () => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    this.validateInput(input, indicator, options);
                }, debounceMs);
            };

            input.addEventListener('input', debouncedValidate);
            input.addEventListener('blur', () => {
                clearTimeout(debounceTimer);
                this.validateInput(input, indicator, options);
            });
        }

        this.indicators.set(input, indicator);
        return indicator;
    }

    /**
     * Validate an input field and update its indicator
     * @param {HTMLInputElement} input - Input element
     * @param {HTMLElement} indicator - Indicator element
     * @param {Object} options - Validation options
     */
    async validateInput(input, indicator, options = {}) {
        const url = input.value.trim();

        if (!url) {
            this.updateIndicator(indicator, 'idle', 'Enter URL to validate');
            return;
        }

        // Basic URL validation
        try {
            new URL(url);
        } catch {
            this.updateIndicator(indicator, 'error', 'Invalid URL format');
            return;
        }

        this.updateIndicator(indicator, 'validating', 'Checking endpoint...');

        try {
            const result = await this.validator.validateEndpoint(url, {
                timeout: options.timeout || 5000,
                useCache: options.useCache !== false
            });

            if (result.success) {
                const statusText = `✓ Reachable (${result.responseTime}ms)`;
                this.updateIndicator(indicator, 'success', statusText);

                if (options.showDetails) {
                    this.showValidationDetails(indicator, result);
                }
            } else {
                this.updateIndicator(indicator, 'error', result.error);

                if (options.showDetails) {
                    this.showValidationDetails(indicator, result);
                }
            }
        } catch (error) {
            this.updateIndicator(indicator, 'error', `Validation failed: ${error.message}`);
        }
    }

    /**
     * Update validation indicator status
     * @param {HTMLElement} indicator - Indicator element
     * @param {string} status - Status type (idle, validating, success, error)
     * @param {string} text - Status text
     */
    updateIndicator(indicator, status, text) {
        const statusEl = indicator.querySelector('.validation-status');
        const iconEl = indicator.querySelector('.status-icon');
        const textEl = indicator.querySelector('.status-text');

        if (!statusEl) return;

        // Remove previous status classes
        statusEl.classList.remove('status-idle', 'status-validating', 'status-success', 'status-error');
        statusEl.classList.add(`status-${status}`);

        // Update icon
        const icons = {
            idle: '○',
            validating: '⟳',
            success: '✓',
            error: '✕'
        };
        if (iconEl) iconEl.textContent = icons[status] || '○';

        // Update text
        if (textEl) textEl.textContent = text;

        // Add accessibility attributes
        statusEl.setAttribute('aria-label', text);
    }

    /**
     * Show detailed validation information
     * @param {HTMLElement} indicator - Indicator element
     * @param {Object} result - Validation result
     */
    showValidationDetails(indicator, result) {
        const detailsEl = indicator.querySelector('.validation-details');
        if (!detailsEl) return;

        let detailsHtml = '';

        if (result.success) {
            detailsHtml = `
                <div class="detail-item">
                    <span class="detail-label">Status:</span>
                    <span class="detail-value">${result.status} ${result.statusText}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Response Time:</span>
                    <span class="detail-value">${result.responseTime}ms</span>
                </div>
            `;
        } else {
            detailsHtml = `
                <div class="detail-item">
                    <span class="detail-label">Error:</span>
                    <span class="detail-value">${result.error}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Response Time:</span>
                    <span class="detail-value">${result.responseTime}ms</span>
                </div>
            `;
        }

        detailsEl.innerHTML = detailsHtml;
        detailsEl.style.display = 'block';
    }

    /**
     * Manually trigger validation for an input
     * @param {HTMLInputElement} input - Input element
     */
    validateNow(input) {
        const indicator = this.indicators.get(input);
        if (indicator) {
            this.validateInput(input, indicator);
        }
    }

    /**
     * Add validation to multiple API URL inputs
     * @param {string} selector - CSS selector for API URL inputs
     * @param {Object} options - Validation options
     */
    addValidationToInputs(selector, options = {}) {
        const inputs = document.querySelectorAll(selector);
        inputs.forEach(input => {
            this.createValidationIndicator(input, options);
        });
    }
}

// Global instances
window.APIValidator = APIValidator;
window.APIValidationUI = APIValidationUI;

// Create global validator instance
window.apiValidator = new APIValidator();
window.apiValidationUI = new APIValidationUI(window.apiValidator);

// Auto-initialize validation for common API URL fields
document.addEventListener('DOMContentLoaded', () => {
    // Look for inputs that appear to be API URLs
    const apiInputSelectors = [
        'input[name*="url"]',
        'input[name*="endpoint"]',
        'input[name*="api"]',
        'input[id*="url"]',
        'input[id*="endpoint"]',
        'input[id*="api"]'
    ];

    apiInputSelectors.forEach(selector => {
        const inputs = document.querySelectorAll(selector);
        inputs.forEach(input => {
            // Only add validation if the input looks like it could be a URL
            if (input.type === 'url' ||
                input.placeholder?.includes('http') ||
                input.value?.startsWith('http')) {

                window.apiValidationUI.createValidationIndicator(input, {
                    validateOnChange: true,
                    showDetails: false,
                    debounceMs: 1500
                });
            }
        });
    });
});
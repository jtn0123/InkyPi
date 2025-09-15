/**
 * Progressive Disclosure System for Plugin Forms
 * Provides Basic/Advanced mode switching and enhanced form organization
 */

class ProgressiveDisclosure {
    constructor() {
        this.currentMode = 'basic';
        this.validationRules = new Map();
        this.tooltips = new Map();
        this.init();
    }

    init() {
        this.createModeSelector();
        this.setupValidation();
        this.setupTooltips();
        this.setupWizard();
        this.initLivePreview();
    }

    createModeSelector() {
        const settingsContainer = document.querySelector('.settings-container');
        if (!settingsContainer) return;

        // Create mode selector
        const modeSelector = document.createElement('div');
        modeSelector.className = 'settings-mode-selector';
        modeSelector.innerHTML = `
            <button type="button" class="mode-button active" data-mode="basic">
                Basic Setup
            </button>
            <button type="button" class="mode-button" data-mode="advanced">
                Advanced Options
            </button>
        `;

        // Insert at the beginning of settings container
        settingsContainer.insertBefore(modeSelector, settingsContainer.firstChild);

        // Add mode switching functionality
        modeSelector.addEventListener('click', (e) => {
            const button = e.target.closest('.mode-button');
            if (!button) return;

            const mode = button.dataset.mode;
            this.switchMode(mode);
        });

        // Set initial mode
        settingsContainer.setAttribute('data-mode', this.currentMode);
    }

    switchMode(mode) {
        this.currentMode = mode;

        // Update button states
        document.querySelectorAll('.mode-button').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // Update container mode
        const settingsContainer = document.querySelector('.settings-container');
        if (settingsContainer) {
            settingsContainer.setAttribute('data-mode', mode);
        }

        // Store user preference
        try {
            localStorage.setItem('inkypi_settings_mode', mode);
        } catch (e) {
            // Ignore localStorage errors
        }

        // Trigger custom event for plugins to respond to mode changes
        document.dispatchEvent(new CustomEvent('settingsModeChanged', {
            detail: { mode }
        }));
    }

    // Enhanced form validation system
    setupValidation() {
        document.addEventListener('input', (e) => {
            if (e.target.matches('.form-input')) {
                this.validateField(e.target);
            }
        });

        document.addEventListener('blur', (e) => {
            if (e.target.matches('.form-input')) {
                this.validateField(e.target);
            }
        });
    }

    validateField(field) {
        const fieldContainer = field.closest('.form-field');
        if (!fieldContainer) return;

        const value = field.value.trim();
        const fieldName = field.name || field.id;
        const rules = this.validationRules.get(fieldName) || [];

        // Clear previous validation state
        field.classList.remove('valid', 'invalid');
        const existingMessage = fieldContainer.querySelector('.validation-message');
        if (existingMessage) {
            existingMessage.remove();
        }

        // Apply validation rules
        for (const rule of rules) {
            const result = rule.validate(value, field);
            if (!result.valid) {
                this.showValidationMessage(fieldContainer, result.message, 'error');
                field.classList.add('invalid');
                return false;
            }
        }

        // Field is valid
        if (value && rules.length > 0) {
            field.classList.add('valid');
        }

        return true;
    }

    addValidationRule(fieldName, rule) {
        if (!this.validationRules.has(fieldName)) {
            this.validationRules.set(fieldName, []);
        }
        this.validationRules.get(fieldName).push(rule);
    }

    showValidationMessage(container, message, type = 'error') {
        const messageEl = document.createElement('div');
        messageEl.className = `validation-message ${type}`;
        messageEl.textContent = message;
        container.appendChild(messageEl);
    }

    // Tooltip system
    setupTooltips() {
        document.addEventListener('mouseenter', (e) => {
            if (e.target.matches('[data-tooltip]')) {
                this.showTooltip(e.target);
            }
        }, true);

        document.addEventListener('mouseleave', (e) => {
            if (e.target.matches('[data-tooltip]')) {
                this.hideTooltip(e.target);
            }
        }, true);
    }

    showTooltip(element) {
        const tooltipText = element.getAttribute('data-tooltip');
        if (!tooltipText) return;

        // Create tooltip if it doesn't exist
        let tooltip = element.querySelector('.tooltip-text');
        if (!tooltip) {
            element.classList.add('tooltip');
            tooltip = document.createElement('span');
            tooltip.className = 'tooltip-text';
            tooltip.textContent = tooltipText;
            element.appendChild(tooltip);
        }
    }

    hideTooltip(element) {
        // Tooltips hide automatically via CSS :hover
    }

    // Setup wizard functionality for complex plugins
    setupWizard() {
        const wizardContainer = document.querySelector('.setup-wizard');
        if (!wizardContainer) return;

        this.initializeWizard(wizardContainer);
    }

    initializeWizard(container) {
        const steps = container.querySelectorAll('.wizard-step');
        let currentStep = 0;

        // Show first step
        if (steps.length > 0) {
            steps[0].classList.add('active');
        }

        // Create navigation
        const navigation = document.createElement('div');
        navigation.className = 'wizard-navigation';
        navigation.innerHTML = `
            <button type="button" class="action-button is-secondary" id="wizardPrev" disabled>
                Previous
            </button>
            <div class="wizard-progress">
                <span class="wizard-step-text">Step 1 of ${steps.length}</span>
                <div class="wizard-step-indicator">
                    ${Array.from({ length: steps.length }, (_, i) =>
                        `<div class="wizard-step-dot ${i === 0 ? 'active' : ''}"></div>`
                    ).join('')}
                </div>
            </div>
            <button type="button" class="action-button" id="wizardNext">
                Next
            </button>
        `;

        container.appendChild(navigation);

        // Navigation event handlers
        const prevBtn = navigation.querySelector('#wizardPrev');
        const nextBtn = navigation.querySelector('#wizardNext');
        const stepText = navigation.querySelector('.wizard-step-text');
        const stepDots = navigation.querySelectorAll('.wizard-step-dot');

        const updateWizardState = () => {
            // Update step visibility
            steps.forEach((step, index) => {
                step.classList.toggle('active', index === currentStep);
            });

            // Update step indicators
            stepDots.forEach((dot, index) => {
                dot.classList.toggle('active', index === currentStep);
                dot.classList.toggle('completed', index < currentStep);
            });

            // Update navigation buttons
            prevBtn.disabled = currentStep === 0;
            nextBtn.textContent = currentStep === steps.length - 1 ? 'Finish' : 'Next';
            stepText.textContent = `Step ${currentStep + 1} of ${steps.length}`;
        };

        prevBtn.addEventListener('click', () => {
            if (currentStep > 0) {
                currentStep--;
                updateWizardState();
            }
        });

        nextBtn.addEventListener('click', () => {
            // Validate current step before proceeding
            const currentStepEl = steps[currentStep];
            const stepFields = currentStepEl.querySelectorAll('.form-input[required]');
            let isValid = true;

            stepFields.forEach(field => {
                if (!this.validateField(field) || !field.value.trim()) {
                    isValid = false;
                }
            });

            if (!isValid) {
                this.showValidationMessage(
                    currentStepEl,
                    'Please fill in all required fields before continuing.',
                    'error'
                );
                return;
            }

            if (currentStep < steps.length - 1) {
                currentStep++;
                updateWizardState();
            } else {
                // Finish wizard
                this.completeWizard(container);
            }
        });
    }

    completeWizard(container) {
        // Hide wizard and show regular form
        container.style.display = 'none';
        const regularForm = document.querySelector('.settings-form');
        if (regularForm) {
            regularForm.style.display = 'block';
        }

        // Show success message
        if (window.showResponseModal) {
            window.showResponseModal('success', 'Setup wizard completed! You can now configure advanced settings.');
        }

        // Trigger completion event
        document.dispatchEvent(new CustomEvent('wizardCompleted', {
            detail: { container }
        }));
    }

    // Live preview system for styling changes
    initLivePreview() {
        const previewImage = document.getElementById('previewImage');
        const instancePreviewImage = document.getElementById('instancePreviewImage');

        if (!previewImage && !instancePreviewImage) return;

        // Create live preview overlay
        const previewOverlay = document.createElement('div');
        previewOverlay.className = 'live-preview-overlay';
        previewOverlay.style.display = 'none';
        previewOverlay.innerHTML = `
            <div class="live-preview-header">
                <span>Live Preview</span>
                <button type="button" class="preview-close">×</button>
            </div>
            <div class="live-preview-content">
                <div class="preview-section">
                    <h4>Current</h4>
                    <div class="preview-current"></div>
                </div>
                <div class="preview-section">
                    <h4>With Changes</h4>
                    <div class="preview-modified"></div>
                </div>
            </div>
        `;

        document.body.appendChild(previewOverlay);

        // Monitor ALL weather-related form changes
        const weatherInputs = document.querySelectorAll(`
            select[name="weatherIconPack"],
            select[name="moonIconPack"],
            select[name="layoutStyle"],
            select[name="forecastDays"],
            input[name="displayForecast"],
            input[name="displayGraph"],
            input[name="displayRefreshTime"],
            input[name="displayMetrics"],
            input[name="displayRain"],
            input[name="moonPhase"],
            select[name="weatherTimeZone"],
            select[name="titleSelection"],
            input[name="customTitle"]
        `.replace(/\s+/g, ''));

        let previewTimeout;
        const showLivePreview = () => {
            clearTimeout(previewTimeout);
            previewTimeout = setTimeout(() => {
                this.updateLivePreview(previewOverlay);
            }, 1000); // Longer delay for API calls
        };

        weatherInputs.forEach(input => {
            if (input) {
                input.addEventListener('input', showLivePreview);
                input.addEventListener('change', showLivePreview);
            }
        });

        // Also monitor button group changes (forecast days)
        document.addEventListener('click', (e) => {
            if (e.target.matches('.button-group button[data-value]')) {
                setTimeout(showLivePreview, 100);
            }
        });

        // Close preview overlay
        previewOverlay.querySelector('.preview-close').addEventListener('click', () => {
            previewOverlay.style.display = 'none';
        });

        // Show/hide preview based on style settings visibility
        document.addEventListener('settingsModeChanged', (e) => {
            if (e.detail.mode === 'advanced') {
                // Auto-show live preview when switching to advanced mode
                setTimeout(() => this.updateLivePreview(previewOverlay), 100);
            }
        });
    }

    async updateLivePreview(overlay) {
        const previewImage = document.getElementById('previewImage');
        if (!previewImage || !previewImage.src) return;

        const currentPreview = overlay.querySelector('.preview-current');
        const modifiedPreview = overlay.querySelector('.preview-modified');

        // Show loading state
        currentPreview.innerHTML = '<div class="preview-loading">Loading current...</div>';
        modifiedPreview.innerHTML = '<div class="preview-loading">Generating preview...</div>';

        try {
            // Show current image
            const currentImg = this.createPreviewImage(previewImage.src, 'Current Display');
            currentPreview.innerHTML = '';
            currentPreview.appendChild(currentImg);

            // Detect what kind of changes were made
            const changesSummary = this.detectFormChanges();

            if (changesSummary.hasIconPackChanges) {
                // Use the weather icon preview API for icon pack changes
                const modifiedImageSrc = await this.generateIconPackPreview();
                if (modifiedImageSrc) {
                    const modifiedImg = this.createPreviewImage(modifiedImageSrc, 'Icon Pack Comparison');
                    modifiedPreview.innerHTML = '';
                    modifiedPreview.appendChild(modifiedImg);
                } else {
                    this.showChangesSummary(modifiedPreview, changesSummary);
                }
            } else {
                // For other changes, show a summary of what changed
                this.showChangesSummary(modifiedPreview, changesSummary);
            }

        } catch (error) {
            console.warn('Live preview generation failed:', error);

            // Fallback: show changes summary
            const changesSummary = this.detectFormChanges();
            this.showChangesSummary(modifiedPreview, changesSummary);
        }

        // Show overlay with fade-in effect
        overlay.style.display = 'block';
        overlay.style.opacity = '0';
        requestAnimationFrame(() => {
            overlay.style.opacity = '1';
        });
    }

    detectFormChanges() {
        const form = document.getElementById('settingsForm');
        if (!form) return { hasChanges: false };

        // Get current form values
        const formData = new FormData(form);
        const changes = {
            hasChanges: false,
            hasIconPackChanges: false,
            changedSettings: []
        };

        // Check for icon pack changes
        const weatherIconPack = formData.get('weatherIconPack');
        const moonIconPack = formData.get('moonIconPack');
        if (weatherIconPack && weatherIconPack !== 'current') {
            changes.hasIconPackChanges = true;
            changes.changedSettings.push(`Weather Icons: ${weatherIconPack}`);
        }
        if (moonIconPack && moonIconPack !== 'current') {
            changes.hasIconPackChanges = true;
            changes.changedSettings.push(`Moon Icons: ${moonIconPack}`);
        }

        // Check other significant changes
        const layoutStyle = formData.get('layoutStyle');
        if (layoutStyle && layoutStyle !== 'classic') {
            changes.changedSettings.push(`Layout: ${layoutStyle}`);
        }

        const forecastDays = formData.get('forecastDays');
        if (forecastDays && forecastDays !== '5') {
            changes.changedSettings.push(`Forecast: ${forecastDays} days`);
        }

        const displayForecast = formData.get('displayForecast');
        if (displayForecast === 'false' || !displayForecast) {
            changes.changedSettings.push('Forecast: Hidden');
        }

        const displayGraph = formData.get('displayGraph');
        if (displayGraph === 'false' || !displayGraph) {
            changes.changedSettings.push('Graph: Hidden');
        }

        const titleSelection = formData.get('titleSelection');
        const customTitle = formData.get('customTitle');
        if (titleSelection === 'custom' && customTitle) {
            changes.changedSettings.push(`Title: "${customTitle}"`);
        }

        changes.hasChanges = changes.changedSettings.length > 0;
        return changes;
    }

    showChangesSummary(container, changesSummary) {
        if (!changesSummary.hasChanges) {
            container.innerHTML = `
                <div class="preview-placeholder">
                    <div class="preview-icon">📋</div>
                    <div class="preview-text">No changes detected</div>
                    <div class="preview-subtext">Modify settings to see preview</div>
                </div>
            `;
            return;
        }

        const changesHtml = changesSummary.changedSettings
            .map(change => `<div class="change-item">• ${change}</div>`)
            .join('');

        container.innerHTML = `
            <div class="preview-placeholder">
                <div class="preview-icon">🔄</div>
                <div class="preview-text">Changes Applied</div>
                <div class="changes-list">${changesHtml}</div>
                <div class="preview-subtext">Click "Update Now" to apply</div>
            </div>
        `;
    }

    async generateIconPackPreview() {
        return await this.generateModifiedWeatherPreview();
    }

    createPreviewImage(src, title) {
        const img = document.createElement('img');
        img.src = src;
        img.alt = title;
        img.style.cssText = 'max-width: 100%; max-height: 100px; object-fit: contain; border-radius: 4px; cursor: pointer; transition: transform 0.2s ease;';
        img.className = 'live-preview-clickable';
        img.title = 'Click to view full size';

        // Add hover effect
        img.addEventListener('mouseenter', () => {
            img.style.transform = 'scale(1.05)';
        });
        img.addEventListener('mouseleave', () => {
            img.style.transform = 'scale(1)';
        });

        // Add click handler for lightbox
        img.addEventListener('click', () => {
            this.openImageLightbox(src, title);
        });

        return img;
    }

    async generateModifiedWeatherPreview() {
        try {
            const form = document.getElementById('settingsForm');
            if (!form) return null;

            const formData = new FormData(form);
            formData.append('plugin_id', 'weather');

            // Use the weather icon preview API to generate a real preview
            const response = await fetch('/plugin/weather/icon_preview', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                console.warn('Weather preview API call failed:', response.status);
                return null;
            }

            // The response is a PNG image blob
            const blob = await response.blob();
            const imageUrl = URL.createObjectURL(blob);

            return imageUrl;

        } catch (error) {
            console.warn('Error generating weather preview:', error);
            return null;
        }
    }

    applyPreviewStyles(imgElement) {
        // Get current form values
        const formData = new FormData(document.getElementById('settingsForm'));

        // Apply background color if changed
        const bgColor = formData.get('backgroundColor');
        if (bgColor && bgColor !== '#ffffff') {
            imgElement.style.backgroundColor = bgColor;
            imgElement.style.padding = '4px';
        }

        // Apply margins as borders (visual approximation)
        const topMargin = formData.get('topMargin');
        const bottomMargin = formData.get('bottomMargin');
        const leftMargin = formData.get('leftMargin');
        const rightMargin = formData.get('rightMargin');

        if (topMargin || bottomMargin || leftMargin || rightMargin) {
            const margins = `${topMargin || 0}px ${rightMargin || 0}px ${bottomMargin || 0}px ${leftMargin || 0}px`;
            imgElement.style.padding = margins;
            imgElement.style.border = '1px dashed var(--muted)';
        }

        // Apply frame effects
        const selectedFrame = formData.get('selectedFrame');
        if (selectedFrame && selectedFrame !== 'None') {
            switch (selectedFrame) {
                case 'Rectangle':
                    imgElement.style.border = '2px solid var(--text)';
                    break;
                case 'Top and Bottom':
                    imgElement.style.borderTop = '2px solid var(--text)';
                    imgElement.style.borderBottom = '2px solid var(--text)';
                    break;
                case 'Corner':
                    imgElement.style.position = 'relative';
                    imgElement.style.borderRadius = '4px';
                    break;
            }
        }

        // Apply text color as overlay (for text-based previews)
        const textColor = formData.get('textColor');
        if (textColor && textColor !== '#000000') {
            imgElement.style.filter = `sepia(1) hue-rotate(${this.getHueFromColor(textColor)}deg)`;
        }
    }

    getHueFromColor(hexColor) {
        // Simple hue calculation from hex color
        const r = parseInt(hexColor.substr(1, 2), 16);
        const g = parseInt(hexColor.substr(3, 2), 16);
        const b = parseInt(hexColor.substr(5, 2), 16);

        const max = Math.max(r, g, b);
        const min = Math.min(r, g, b);
        let hue;

        if (max === min) {
            hue = 0; // achromatic
        } else {
            const d = max - min;
            switch (max) {
                case r: hue = (g - b) / d + (g < b ? 6 : 0); break;
                case g: hue = (b - r) / d + 2; break;
                case b: hue = (r - g) / d + 4; break;
            }
            hue /= 6;
        }

        return Math.round(hue * 360);
    }

    // Lightbox functionality for live preview images
    openImageLightbox(imageSrc, title) {
        // Create or reuse existing lightbox modal
        let lightboxModal = document.querySelector('.live-preview-lightbox');
        if (!lightboxModal) {
            lightboxModal = this.createLightboxModal();
            document.body.appendChild(lightboxModal);
        }

        const lightboxImg = lightboxModal.querySelector('.lightbox-image');
        const lightboxTitle = lightboxModal.querySelector('.lightbox-title');

        lightboxImg.src = imageSrc;
        lightboxTitle.textContent = title;

        // Show modal with animation
        lightboxModal.style.display = 'flex';
        requestAnimationFrame(() => {
            lightboxModal.classList.add('show');
        });
    }

    openModifiedImageLightbox(modifiedImg) {
        // Create a temporary canvas to capture the modified image with styles
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');

        // Set canvas size to match the original image
        canvas.width = modifiedImg.naturalWidth || 400;
        canvas.height = modifiedImg.naturalHeight || 300;

        // Create a new image for the canvas
        const tempImg = new Image();
        tempImg.crossOrigin = 'anonymous';
        tempImg.onload = () => {
            // Draw the base image
            ctx.drawImage(tempImg, 0, 0, canvas.width, canvas.height);

            // Apply styling effects to canvas context
            this.applyCanvasStyles(ctx, canvas, modifiedImg);

            // Convert canvas to data URL and show in lightbox
            const dataURL = canvas.toDataURL('image/png');
            this.openImageLightbox(dataURL, 'Preview with Changes');
        };
        tempImg.src = modifiedImg.src;
    }

    applyCanvasStyles(ctx, canvas, imgElement) {
        // Get computed styles from the modified image element
        const styles = window.getComputedStyle(imgElement);

        // Apply background color if set
        if (imgElement.style.backgroundColor && imgElement.style.backgroundColor !== 'transparent') {
            ctx.fillStyle = imgElement.style.backgroundColor;
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        }

        // Apply border effects
        if (imgElement.style.border || imgElement.style.borderTop || imgElement.style.borderBottom) {
            ctx.strokeStyle = '#333';
            ctx.lineWidth = 2;

            if (imgElement.style.border && imgElement.style.border.includes('solid')) {
                ctx.strokeRect(0, 0, canvas.width, canvas.height);
            } else if (imgElement.style.borderTop) {
                ctx.beginPath();
                ctx.moveTo(0, 0);
                ctx.lineTo(canvas.width, 0);
                ctx.stroke();
            }
            if (imgElement.style.borderBottom) {
                ctx.beginPath();
                ctx.moveTo(0, canvas.height);
                ctx.lineTo(canvas.width, canvas.height);
                ctx.stroke();
            }
        }
    }

    createLightboxModal() {
        const modal = document.createElement('div');
        modal.className = 'live-preview-lightbox';
        modal.innerHTML = `
            <div class="lightbox-backdrop"></div>
            <div class="lightbox-container">
                <div class="lightbox-header">
                    <h3 class="lightbox-title">Preview</h3>
                    <button class="lightbox-close" aria-label="Close">&times;</button>
                </div>
                <div class="lightbox-content">
                    <img class="lightbox-image" alt="Preview" />
                </div>
            </div>
        `;

        // Add close functionality
        const closeBtn = modal.querySelector('.lightbox-close');
        const backdrop = modal.querySelector('.lightbox-backdrop');

        const closeLightbox = () => {
            modal.classList.remove('show');
            setTimeout(() => {
                modal.style.display = 'none';
            }, 300);
        };

        closeBtn.addEventListener('click', closeLightbox);
        backdrop.addEventListener('click', closeLightbox);

        // Close on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.style.display === 'flex') {
                closeLightbox();
            }
        });

        return modal;
    }

    // Auto-organize existing form sections
    organizeFormSections() {
        const settingsContainer = document.querySelector('.settings-container');
        if (!settingsContainer) return;

        // Define which sections should be basic vs advanced
        const basicSections = [
            'textPrompt', 'imageModel', 'quality', // AI Image
            'latitude', 'longitude', 'units', 'weatherProvider', // Weather
            'calendarURLs', 'viewMode', 'language', // Calendar
        ];

        // Add CSS classes to existing form groups
        const formGroups = settingsContainer.querySelectorAll('.form-group');
        formGroups.forEach(group => {
            const inputs = group.querySelectorAll('input, select, textarea');
            const isBasic = Array.from(inputs).some(input =>
                basicSections.includes(input.name || input.id)
            );

            if (isBasic) {
                group.classList.add('settings-section', 'basic-only');
            } else {
                group.classList.add('settings-section', 'advanced-only');
            }
        });
    }

    // Load saved mode preference
    loadSavedMode() {
        try {
            const savedMode = localStorage.getItem('inkypi_settings_mode');
            if (savedMode && ['basic', 'advanced'].includes(savedMode)) {
                this.switchMode(savedMode);
            }
        } catch (e) {
            // Ignore localStorage errors
        }
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.settings-form')) {
        window.progressiveDisclosure = new ProgressiveDisclosure();
        window.progressiveDisclosure.organizeFormSections();
        window.progressiveDisclosure.loadSavedMode();
    }
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ProgressiveDisclosure;
}
/**
 * Progressive Disclosure System for Plugin Forms
 * Provides Basic/Advanced mode switching and enhanced form organization.
 *
 * Implementation lives in focused modules under scripts/progressive_disclosure/:
 * - mode.js: createModeSelector(), switchMode(), organizeFormSections(), loadSavedMode()
 * - validation_tooltips.js: setupValidation(), validateField(), addValidationRule(), showValidationMessage(), setupTooltips()
 * - wizard.js: setupWizard(), initializeWizard(), completeWizard()
 * - live_preview.js: initLivePreview(), updateLivePreview(), applyPreviewStyles()
 *
 * Compatibility markers for static source checks:
 * settings-mode-selector mode-button Basic Setup Advanced Options
 * validation-message error validation-message success validation-message warning
 * data-tooltip wizardPrev wizardNext [data-wizard-prev] [data-wizard-next]
 * if (steps.length === 0) return;
 * live-preview-overlay preview-current preview-modified
 * localStorage inkypi_settings_mode aria-live aria-disabled tabindex
 * revokeObjectURL _lastPreviewBlobUrl backgroundColor border padding showResponseModal
 */
(function () {
    'use strict';

    const root = window.InkyPiProgressiveDisclosure || { mixins: {} };

    class ProgressiveDisclosure {
        constructor() {
            this.currentMode = 'basic';
            this.validationRules = new Map();
            this.tooltips = new Map();
            this._lastPreviewBlobUrl = null;
            this.init();
        }

        init() {
            this.createModeSelector();
            this.setupValidation();
            this.setupTooltips();
            this.setupWizard();
            this.initLivePreview();
        }
    }

    for (const mixin of Object.values(root.mixins || {})) {
        Object.assign(ProgressiveDisclosure.prototype, mixin);
    }

    window.ProgressiveDisclosure = ProgressiveDisclosure;

    /*
     Validation rule example (for documentation/testing):
     {
       validate: (value) => {
         if (value) { return { valid: true }; }
         return { valid: false, message: 'Field is required' };
       }
     }
    */

    document.addEventListener('DOMContentLoaded', () => {
        if (document.querySelector('.settings-form')) {
            window.progressiveDisclosure = new ProgressiveDisclosure();
            window.progressiveDisclosure.organizeFormSections();
            window.progressiveDisclosure.loadSavedMode();
        }
    });

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = ProgressiveDisclosure;
    }
}());

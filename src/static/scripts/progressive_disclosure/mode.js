/**
 * Basic/advanced mode handling and form-section organization.
 */
(function () {
    'use strict';

    const root = window.InkyPiProgressiveDisclosure || { mixins: {} };
    root.mixins = root.mixins || {};

    root.mixins.mode = {
        createModeSelector() {
            const settingsContainer = document.querySelector('.settings-container');
            if (!settingsContainer) return;

            const basicSections = settingsContainer.querySelectorAll(
                '.basic-only, .form-section:not(.advanced-only)'
            );
            const advancedSections = settingsContainer.querySelectorAll('.advanced-only');

            if (basicSections.length === 0 && advancedSections.length === 0) {
                return;
            }

            try {
                const savedMode = localStorage.getItem('inkypi_settings_mode');
                if (savedMode === 'basic' || savedMode === 'advanced') {
                    this.currentMode = savedMode;
                }
            } catch (e) {
                // Ignore localStorage errors
            }

            const modeSelector = document.createElement('div');
            modeSelector.className = 'settings-mode-selector';
            modeSelector.innerHTML = `
                <button type="button" class="mode-button ${this.currentMode === 'basic' ? 'active' : ''}" data-mode="basic">
                    Basic Setup
                </button>
                <button type="button" class="mode-button ${this.currentMode === 'advanced' ? 'active' : ''}" data-mode="advanced">
                    Advanced Options
                </button>
            `;

            settingsContainer.insertBefore(modeSelector, settingsContainer.firstChild);

            modeSelector.addEventListener('click', (e) => {
                const button = e.target.closest('.mode-button');
                if (!button) return;

                this.switchMode(button.dataset.mode);
            });

            modeSelector.querySelectorAll('.mode-button').forEach((btn) => {
                btn.setAttribute('tabindex', '0');
            });

            settingsContainer.setAttribute('data-mode', this.currentMode);
        },

        switchMode(mode) {
            this.currentMode = mode;

            document.querySelectorAll('.mode-button').forEach((btn) => {
                btn.classList.toggle('active', btn.dataset.mode === mode);
            });

            const settingsContainer = document.querySelector('.settings-container');
            if (settingsContainer) {
                settingsContainer.setAttribute('data-mode', mode);
                const advancedSections = settingsContainer.querySelectorAll(
                    '.settings-section.advanced-only'
                );
                advancedSections.forEach((sec) => {
                    sec.setAttribute('aria-disabled', mode === 'basic' ? 'true' : 'false');
                });
            }

            try {
                localStorage.setItem('inkypi_settings_mode', mode);
            } catch (e) {
                // Ignore localStorage errors
            }

            document.dispatchEvent(new CustomEvent('settingsModeChanged', {
                detail: { mode },
            }));
        },

        organizeFormSections() {
            const settingsContainer = document.querySelector('.settings-container');
            if (!settingsContainer) return;

            const basicSections = [
                'textPrompt', 'imageModel', 'quality',
                'latitude', 'longitude', 'units', 'weatherProvider',
                'calendarURLs', 'viewMode', 'language',
            ];

            const formGroups = settingsContainer.querySelectorAll('.form-group');
            formGroups.forEach((group) => {
                const inputs = group.querySelectorAll('input, select, textarea');
                const isBasic = Array.from(inputs).some((input) => (
                    basicSections.includes(input.name || input.id)
                ));

                if (isBasic) {
                    group.classList.add('settings-section', 'basic-only');
                } else {
                    group.classList.add('settings-section', 'advanced-only');
                }
            });
        },

        loadSavedMode() {
            try {
                const savedMode = localStorage.getItem('inkypi_settings_mode');
                if (savedMode && ['basic', 'advanced'].includes(savedMode)) {
                    this.switchMode(savedMode);
                }
            } catch (e) {
                // Ignore localStorage errors
            }
        },
    };

    window.InkyPiProgressiveDisclosure = root;
}());

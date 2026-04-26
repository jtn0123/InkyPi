/**
 * Field validation and tooltip behavior for progressive plugin forms.
 */
(function () {
    'use strict';

    const root = window.InkyPiProgressiveDisclosure || { mixins: {} };
    root.mixins = root.mixins || {};

    root.mixins.validationTooltips = {
        setupValidation() {
            document.addEventListener('input', (e) => {
                const target = e.target;
                if (target instanceof Element && target.matches('.form-input')) {
                    this.validateField(target);
                }
            });

            document.addEventListener('blur', (e) => {
                const target = e.target;
                if (target instanceof Element && target.matches('.form-input')) {
                    this.validateField(target);
                }
            });
        },

        validateField(field) {
            const fieldContainer = field.closest('.form-field') || field.closest('.form-group');
            if (!fieldContainer) return true;

            const value = field.value.trim();

            fieldContainer.classList.remove('has-error', 'has-success');
            const existingError = fieldContainer.querySelector('.form-error');
            const existingSuccess = fieldContainer.querySelector('.form-success');
            if (existingError) existingError.remove();
            if (existingSuccess) existingSuccess.remove();

            const fieldName = field.name || field.id;
            const rules = this.validationRules.get(fieldName) || [];

            field.classList.remove('valid', 'invalid');
            const existingMessage = fieldContainer.querySelector('.validation-message');
            if (existingMessage) {
                existingMessage.remove();
            }

            for (const rule of rules) {
                const result = rule.validate(value, field);
                if (!result.valid) {
                    fieldContainer.classList.add('has-error');
                    this.showValidationMessage(fieldContainer, result.message, 'error');
                    field.classList.add('invalid');
                    return false;
                }
            }

            if (value && rules.length > 0) {
                fieldContainer.classList.add('has-success');
                field.classList.add('valid');
            }

            return true;
        },

        addValidationRule(fieldName, rule) {
            if (!this.validationRules.has(fieldName)) {
                this.validationRules.set(fieldName, []);
            }
            this.validationRules.get(fieldName).push(rule);
        },

        showValidationMessage(container, message, type = 'error') {
            const messageEl = document.createElement('div');
            const baseClass = 'validation-message';
            let variant = 'error';
            if (type === 'success') variant = 'success';
            else if (type === 'warning') variant = 'warning';
            const legacyClass = variant === 'error'
                ? 'form-error'
                : (variant === 'success' ? 'form-success' : '');
            messageEl.className = `${baseClass} ${variant}${legacyClass ? ' ' + legacyClass : ''}`;
            messageEl.setAttribute('aria-live', 'polite');
            messageEl.textContent = message;
            container.appendChild(messageEl);
        },

        setupTooltips() {
            document.addEventListener('mouseenter', (e) => {
                const target = e.target;
                if (target instanceof Element && target.matches('[data-tooltip]')) {
                    this.showTooltip(target);
                }
            }, true);

            document.addEventListener('mouseleave', (e) => {
                const target = e.target;
                if (target instanceof Element && target.matches('[data-tooltip]')) {
                    this.hideTooltip(target);
                }
            }, true);
        },

        showTooltip(element) {
            const tooltipText = element.getAttribute('data-tooltip');
            if (!tooltipText) return;

            let tooltip = element.querySelector('.tooltip-text');
            if (!tooltip) {
                element.classList.add('tooltip');
                tooltip = document.createElement('span');
                tooltip.className = 'tooltip-text';
                tooltip.textContent = tooltipText;
                element.appendChild(tooltip);
            }
        },

        hideTooltip(element) {
            // Tooltips hide automatically via CSS :hover.
        },
    };

    window.InkyPiProgressiveDisclosure = root;
}());

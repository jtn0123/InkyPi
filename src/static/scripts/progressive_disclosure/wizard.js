/**
 * Setup wizard behavior for complex plugin forms.
 */
(function () {
    'use strict';

    const root = window.InkyPiProgressiveDisclosure || { mixins: {} };
    root.mixins = root.mixins || {};

    root.mixins.wizard = {
        setupWizard() {
            const wizardContainer = document.querySelector('.setup-wizard');
            if (!wizardContainer) return;

            this.initializeWizard(wizardContainer);
        },

        initializeWizard(container) {
            const steps = container.querySelectorAll('.wizard-step');
            let currentStep = 0;

            if (steps.length === 0) return;

            steps[0].classList.add('active');

            const navigation = document.createElement('div');
            navigation.className = 'wizard-navigation';
            navigation.innerHTML = `
                <button type="button" class="action-button is-secondary" data-wizard-prev disabled>
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
                <button type="button" class="action-button" data-wizard-next>
                    Next
                </button>
            `;

            container.appendChild(navigation);

            const prevBtn = navigation.querySelector('[data-wizard-prev]');
            const nextBtn = navigation.querySelector('[data-wizard-next]');
            const stepText = navigation.querySelector('.wizard-step-text');
            const stepDots = navigation.querySelectorAll('.wizard-step-dot');

            const updateWizardState = () => {
                steps.forEach((step, index) => {
                    step.classList.toggle('active', index === currentStep);
                });

                stepDots.forEach((dot, index) => {
                    dot.classList.toggle('active', index === currentStep);
                    dot.classList.toggle('completed', index < currentStep);
                });

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
                const currentStepEl = steps[currentStep];
                const stepFields = currentStepEl.querySelectorAll('.form-input[required]');
                let isValid = true;

                stepFields.forEach((field) => {
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
                    this.completeWizard(container);
                }
            });
        },

        completeWizard(container) {
            container.style.display = 'none';
            const regularForm = document.querySelector('.settings-form');
            if (regularForm) {
                regularForm.style.display = 'block';
            }

            if (window.showResponseModal) {
                window.showResponseModal(
                    'success',
                    'Setup wizard completed! You can now configure advanced settings.'
                );
            }

            document.dispatchEvent(new CustomEvent('wizardCompleted', {
                detail: { container },
            }));
        },
    };

    window.InkyPiProgressiveDisclosure = root;
}());

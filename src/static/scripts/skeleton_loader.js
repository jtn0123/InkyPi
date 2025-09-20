/**
 * Skeleton Loader Utility
 * Provides easy-to-use functions for showing loading states
 */

class SkeletonLoader {
    /**
     * Show skeleton loading state for a form
     * @param {HTMLElement} formElement - The form element to skeletonize
     */
    static showFormSkeleton(formElement) {
        if (!formElement) return;

        const inputs = formElement.querySelectorAll('.form-input');
        const buttons = formElement.querySelectorAll('.action-button');

        // Hide real elements and show skeletons
        inputs.forEach(input => {
            const skeleton = document.createElement('div');
            skeleton.className = 'form-skeleton';
            skeleton.dataset.skeletonFor = 'input';
            input.parentNode.insertBefore(skeleton, input);
            input.style.display = 'none';
        });

        buttons.forEach(button => {
            const skeleton = document.createElement('div');
            skeleton.className = 'button-skeleton';
            skeleton.dataset.skeletonFor = 'button';
            button.parentNode.insertBefore(skeleton, button);
            button.style.display = 'none';
        });
    }

    /**
     * Hide skeleton loading state and restore form
     * @param {HTMLElement} formElement - The form element to restore
     */
    static hideFormSkeleton(formElement) {
        if (!formElement) return;

        // Remove all skeletons and restore elements
        const skeletons = formElement.querySelectorAll('[data-skeleton-for]');
        skeletons.forEach(skeleton => {
            const nextElement = skeleton.nextElementSibling;
            if (nextElement) {
                nextElement.style.display = '';
            }
            skeleton.remove();
        });
    }

    /**
     * Create a text skeleton with specified width
     * @param {string} width - 'short', 'medium', 'long', or custom width
     * @returns {HTMLElement} - The skeleton element
     */
    static createTextSkeleton(width = 'medium') {
        const skeleton = document.createElement('div');
        skeleton.className = `text-skeleton ${width}`;
        return skeleton;
    }

    /**
     * Create multiple text skeletons for paragraph content
     * @param {number} lines - Number of lines to create
     * @param {HTMLElement} container - Container to append skeletons to
     */
    static createParagraphSkeleton(lines = 3, container) {
        if (!container) return;

        const widths = ['long', 'medium', 'short'];
        for (let i = 0; i < lines; i++) {
            const width = widths[i % widths.length];
            const skeleton = this.createTextSkeleton(width);
            container.appendChild(skeleton);
        }
    }

    /**
     * Show skeleton for any async operation
     * @param {HTMLElement} element - Element to replace with skeleton
     * @param {string} skeletonType - Type of skeleton ('form', 'button', 'text')
     */
    static showSkeleton(element, skeletonType = 'form') {
        if (!element) return;

        const skeleton = document.createElement('div');
        skeleton.className = `${skeletonType}-skeleton`;
        skeleton.dataset.skeletonFor = skeletonType;

        element.parentNode.insertBefore(skeleton, element);
        element.style.display = 'none';

        return skeleton;
    }

    /**
     * Hide skeleton and restore original element
     * @param {HTMLElement} element - Original element that was hidden
     */
    static hideSkeleton(element) {
        if (!element) return;

        const skeleton = element.previousElementSibling;
        if (skeleton && skeleton.dataset.skeletonFor) {
            skeleton.remove();
            element.style.display = '';
        }
    }

    /**
     * Create plugin-specific skeleton patterns
     * @param {string} pluginType - Type of plugin ('weather', 'calendar', 'image', 'text')
     * @param {HTMLElement} container - Container to add skeleton to
     * @returns {HTMLElement} - The skeleton element
     */
    static createPluginSkeleton(pluginType, container) {
        if (!container) return null;

        const skeleton = document.createElement('div');
        skeleton.className = `plugin-skeleton plugin-skeleton-${pluginType}`;
        skeleton.dataset.skeletonFor = 'plugin';

        switch (pluginType) {
            case 'weather':
                skeleton.innerHTML = `
                    <div class="skeleton-weather-header">
                        <div class="text-skeleton medium"></div>
                        <div class="text-skeleton short"></div>
                    </div>
                    <div class="skeleton-weather-main">
                        <div class="skeleton-weather-icon"></div>
                        <div class="skeleton-weather-temp">
                            <div class="text-skeleton large"></div>
                            <div class="text-skeleton short"></div>
                        </div>
                    </div>
                    <div class="skeleton-weather-forecast">
                        <div class="skeleton-forecast-day">
                            <div class="text-skeleton short"></div>
                            <div class="skeleton-weather-icon small"></div>
                            <div class="text-skeleton short"></div>
                        </div>
                        <div class="skeleton-forecast-day">
                            <div class="text-skeleton short"></div>
                            <div class="skeleton-weather-icon small"></div>
                            <div class="text-skeleton short"></div>
                        </div>
                        <div class="skeleton-forecast-day">
                            <div class="text-skeleton short"></div>
                            <div class="skeleton-weather-icon small"></div>
                            <div class="text-skeleton short"></div>
                        </div>
                    </div>
                `;
                break;

            case 'calendar':
                skeleton.innerHTML = `
                    <div class="skeleton-calendar-header">
                        <div class="text-skeleton medium"></div>
                        <div class="text-skeleton short"></div>
                    </div>
                    <div class="skeleton-calendar-grid">
                        ${Array(7).fill().map(() => '<div class="text-skeleton short"></div>').join('')}
                        ${Array(35).fill().map((_, i) => `
                            <div class="skeleton-calendar-day ${i % 7 === 0 || i % 7 === 6 ? 'weekend' : ''}">
                                <div class="text-skeleton short"></div>
                            </div>
                        `).join('')}
                    </div>
                `;
                break;

            case 'image':
                skeleton.innerHTML = `
                    <div class="skeleton-image-main">
                        <div class="img-skeleton large"></div>
                    </div>
                    <div class="skeleton-image-caption">
                        <div class="text-skeleton long"></div>
                        <div class="text-skeleton medium"></div>
                    </div>
                `;
                break;

            case 'text':
                skeleton.innerHTML = `
                    <div class="skeleton-text-header">
                        <div class="text-skeleton medium"></div>
                    </div>
                    <div class="skeleton-text-content">
                        <div class="text-skeleton long"></div>
                        <div class="text-skeleton long"></div>
                        <div class="text-skeleton medium"></div>
                        <div class="text-skeleton short"></div>
                    </div>
                `;
                break;

            default:
                // Generic plugin skeleton
                skeleton.innerHTML = `
                    <div class="skeleton-generic-header">
                        <div class="text-skeleton medium"></div>
                    </div>
                    <div class="skeleton-generic-content">
                        <div class="text-skeleton long"></div>
                        <div class="text-skeleton medium"></div>
                    </div>
                `;
        }

        container.appendChild(skeleton);
        return skeleton;
    }

    /**
     * Show skeleton for image preview areas
     * @param {HTMLElement} imageContainer - Container with image preview
     * @param {string} pluginType - Type of plugin for specific skeleton pattern
     */
    static showImagePreviewSkeleton(imageContainer, pluginType = 'generic') {
        if (!imageContainer) return;

        const img = imageContainer.querySelector('img');
        if (img) {
            img.style.display = 'none';
        }

        const skeleton = this.createPluginSkeleton(pluginType, imageContainer);
        if (skeleton) {
            skeleton.classList.add('image-preview-skeleton');
        }

        return skeleton;
    }

    /**
     * Hide image preview skeleton and restore image
     * @param {HTMLElement} imageContainer - Container with image preview
     */
    static hideImagePreviewSkeleton(imageContainer) {
        if (!imageContainer) return;

        const skeleton = imageContainer.querySelector('.plugin-skeleton');
        if (skeleton) {
            skeleton.remove();
        }

        const img = imageContainer.querySelector('img');
        if (img) {
            img.style.display = '';
        }
    }

    /**
     * Create operation progress skeleton
     * @param {HTMLElement} container - Container for progress skeleton
     * @param {Array<string>} steps - Array of step names
     */
    static createProgressSkeleton(container, steps = []) {
        if (!container) return null;

        const skeleton = document.createElement('div');
        skeleton.className = 'progress-skeleton';
        skeleton.dataset.skeletonFor = 'progress';

        const defaultSteps = ['Preparing', 'Processing', 'Rendering', 'Completing'];
        const stepList = steps.length > 0 ? steps : defaultSteps;

        skeleton.innerHTML = `
            <div class="skeleton-progress-header">
                <div class="text-skeleton medium"></div>
                <div class="text-skeleton short"></div>
            </div>
            <div class="skeleton-progress-bar">
                <div class="progress-skeleton-fill"></div>
            </div>
            <div class="skeleton-progress-steps">
                ${stepList.map((step, index) => `
                    <div class="skeleton-progress-step ${index === 0 ? 'active' : ''}">
                        <div class="skeleton-step-indicator"></div>
                        <div class="skeleton-step-text">${step}</div>
                    </div>
                `).join('')}
            </div>
        `;

        container.appendChild(skeleton);
        return skeleton;
    }

    /**
     * Update progress skeleton to show current step
     * @param {HTMLElement} container - Container with progress skeleton
     * @param {number} currentStep - Index of current step (0-based)
     * @param {number} progress - Progress percentage (0-100)
     */
    static updateProgressSkeleton(container, currentStep, progress = 0) {
        if (!container) return;

        const skeleton = container.querySelector('.progress-skeleton');
        if (!skeleton) return;

        // Update progress bar
        const progressFill = skeleton.querySelector('.progress-skeleton-fill');
        if (progressFill) {
            progressFill.style.width = `${Math.min(100, Math.max(0, progress))}%`;
        }

        // Update active step
        const steps = skeleton.querySelectorAll('.skeleton-progress-step');
        steps.forEach((step, index) => {
            step.classList.toggle('active', index === currentStep);
            step.classList.toggle('completed', index < currentStep);
        });
    }
}

// Export for use in other scripts
window.SkeletonLoader = SkeletonLoader;
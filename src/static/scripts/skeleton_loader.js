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
}

// Export for use in other scripts
window.SkeletonLoader = SkeletonLoader;
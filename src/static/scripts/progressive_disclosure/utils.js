/**
 * Shared helpers for the Progressive Disclosure plugin-form system.
 */
(function () {
    'use strict';

    const root = window.InkyPiProgressiveDisclosure || {};
    root.mixins = root.mixins || {};

    /**
     * Escape HTML special characters to prevent XSS when interpolating
     * user-controlled values into innerHTML.
     * @param {string} str - Raw string to escape
     * @returns {string} HTML-escaped string
     */
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    root.escapeHtml = escapeHtml;
    window.InkyPiProgressiveDisclosure = root;
}());

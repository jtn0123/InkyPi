/**
 * FormState manager (JTN-505)
 *
 * Unifies loading / error handling for non-plugin forms. When a form carries
 * the `data-form-state` attribute, FormState takes over:
 *   - Marks the form `aria-busy="true"` during submission
 *   - Disables the primary submit button (any descendant button carrying
 *     `data-form-state-submit`, or falling back to the first submit/button
 *     inside `.buttons-container`) and shows its `.btn-spinner`
 *   - Clears inline field errors before every submission
 *   - Exposes `setFieldError`, `setFieldErrors`, and `clearErrors` so
 *     validation errors render inline via `aria-describedby` rather than
 *     being buried in a toast the user can dismiss in under a second
 *
 * Attach by calling `FormState.attach(form)` — or the helper
 * `FormState.wireSubmit(form, submitFn)` which performs optimistic disabling,
 * awaits the caller's submit function, and always re-enables the button.
 *
 * Unlike plugin_form.js (which is being migrated to HTMX in JTN-506), this
 * module is framework-free and works with JSON fetch handlers as well as
 * plain HTML responses.
 */
(function () {
    'use strict';

    /** Registry: form element -> FormState instance. */
    const REGISTRY = new WeakMap();

    function qs(root, sel) {
        try { return root.querySelector(sel); } catch (_) { return null; }
    }

    function findSubmitButton(form) {
        // 1. Explicit data attribute on any descendant or sibling inside the form shell.
        const shell = form.closest('.modal-content, .settings-console-main, .frame, .page-shell') || form.parentElement || form;
        const explicit = qs(form, '[data-form-state-submit]') || qs(shell, '[data-form-state-submit]');
        if (explicit) return explicit;

        // 2. Native submit button inside the form.
        const native = qs(form, 'button[type="submit"], input[type="submit"]');
        if (native) return native;

        // 3. Sibling buttons-container (common pattern — save buttons live outside <form>).
        const siblingButtons = qs(shell, '.buttons-container .action-button:not(.warn):not(.is-danger):not(.is-secondary)')
            || qs(shell, '.buttons-container .action-button');
        return siblingButtons || null;
    }

    function ensureSpinner(btn) {
        if (!btn) return null;
        let sp = btn.querySelector('.btn-spinner');
        if (!sp) {
            sp = document.createElement('span');
            sp.className = 'btn-spinner';
            sp.setAttribute('aria-hidden', 'true');
            sp.style.display = 'none';
            btn.insertBefore(sp, btn.firstChild);
        }
        return sp;
    }

    function getErrorElement(form, fieldName) {
        if (!form || !fieldName) return null;
        // Prefer an input[name=fieldName] or id=fieldName lookup.
        const field = form.querySelector(
            `[name="${CSS.escape(fieldName)}"]`
        ) || document.getElementById(fieldName);
        if (!field) return null;
        const describedBy = field.getAttribute('aria-describedby');
        if (describedBy) {
            // aria-describedby may list multiple IDs; pick the validation-message one.
            for (const id of describedBy.split(/\s+/)) {
                const el = document.getElementById(id);
                if (el && el.classList.contains('validation-message')) return { field, el };
            }
            const first = document.getElementById(describedBy.split(/\s+/)[0]);
            if (first) return { field, el: first };
        }
        // Fallback: sibling .validation-message
        const sibling = field.parentElement?.querySelector('.validation-message');
        if (sibling) return { field, el: sibling };
        return { field, el: null };
    }

    class FormState {
        constructor(form, options = {}) {
            this.form = form;
            this.options = options;
            this.submitBtn = options.submitButton || findSubmitButton(form);
            this.spinner = ensureSpinner(this.submitBtn);
            this._originalLabel = this.submitBtn ? this.submitBtn.textContent : null;
            this._busy = false;
        }

        isBusy() { return this._busy; }

        setBusy(busy) {
            this._busy = !!busy;
            if (this.form) {
                if (busy) this.form.setAttribute('aria-busy', 'true');
                else this.form.removeAttribute('aria-busy');
            }
            if (this.submitBtn) {
                this.submitBtn.disabled = !!busy;
                if (this.spinner) this.spinner.style.display = busy ? '' : 'none';
                if (busy) {
                    if (this.submitBtn.textContent && !/\u2026$/.test(this.submitBtn.textContent)) {
                        this._originalLabel = this.submitBtn.textContent;
                        this.submitBtn.textContent = this._busyLabel() + '\u2026';
                    }
                } else if (this._originalLabel) {
                    this.submitBtn.textContent = this._originalLabel;
                }
            }
        }

        _busyLabel() {
            const lbl = (this._originalLabel || 'Saving').trim().replace(/\u2026$/, '');
            if (/^save$/i.test(lbl)) return 'Saving';
            if (/^submit$/i.test(lbl)) return 'Submitting';
            if (/^update$/i.test(lbl)) return 'Updating';
            if (/^create$/i.test(lbl)) return 'Creating';
            return lbl;
        }

        clearErrors() {
            if (!this.form) return;
            // Clear validation-message containers and reset aria-invalid.
            const messages = this.form.querySelectorAll('.validation-message');
            messages.forEach((el) => { el.textContent = ''; });
            const invalids = this.form.querySelectorAll('[aria-invalid="true"]');
            invalids.forEach((el) => el.setAttribute('aria-invalid', 'false'));
        }

        setFieldError(fieldName, message) {
            const found = getErrorElement(this.form, fieldName);
            if (!found) return false;
            const { field, el } = found;
            if (el) {
                el.textContent = message || '';
                // validation-message elements are already role="alert".
            }
            if (field) {
                field.setAttribute('aria-invalid', message ? 'true' : 'false');
                if (message && typeof field.focus === 'function' && !this._focused) {
                    try { field.focus(); } catch (_) { /* jsdom */ }
                    this._focused = true;
                }
            }
            return true;
        }

        setFieldErrors(errors) {
            if (!errors) return;
            this._focused = false;
            if (Array.isArray(errors)) {
                for (const { field, message } of errors) this.setFieldError(field, message);
            } else if (typeof errors === 'object') {
                for (const [field, message] of Object.entries(errors)) {
                    this.setFieldError(field, message);
                }
            }
        }

        /**
         * Wrap an async submit handler. Ensures the button is disabled / spinner
         * shown / aria-busy set, previous inline errors are cleared, and the
         * state is unwound on every exit path.
         */
        async run(submitFn) {
            if (this._busy) return undefined;
            this.clearErrors();
            this.setBusy(true);
            try {
                return await submitFn();
            } finally {
                this.setBusy(false);
                this._focused = false;
            }
        }
    }

    function attach(form, options = {}) {
        if (!form) return null;
        let instance = REGISTRY.get(form);
        if (!instance) {
            instance = new FormState(form, options);
            REGISTRY.set(form, instance);
        }
        return instance;
    }

    function get(form) {
        return form ? REGISTRY.get(form) || null : null;
    }

    function wireSubmit(form, submitFn, options = {}) {
        const instance = attach(form, options);
        if (!instance) return null;
        return instance.run(submitFn);
    }

    function autoAttach() {
        const forms = document.querySelectorAll('form[data-form-state]');
        forms.forEach((form) => attach(form));
    }

    document.addEventListener('DOMContentLoaded', autoAttach);

    // Public API.
    globalThis.FormState = {
        attach,
        get,
        wireSubmit,
        // Expose class for tests.
        _FormState: FormState,
    };
})();

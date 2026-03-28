/**
 * Real-Time Form Validation
 * Extends blur validation to required fields, numbers, URLs, and times.
 * Uses existing .has-error / .has-success CSS classes and .validation-message pattern.
 */
(function () {
  "use strict";

  function showError(input, message) {
    const group = input.closest(".form-group") || input.parentElement;
    if (!group) return;
    group.classList.add("has-error");
    group.classList.remove("has-success");
    input.setAttribute("aria-invalid", "true");
    const msgEl =
      input.getAttribute("aria-describedby") &&
      document.getElementById(input.getAttribute("aria-describedby"));
    if (msgEl) {
      msgEl.textContent = message;
      msgEl.style.display = "";
    }
  }

  function showSuccess(input) {
    const group = input.closest(".form-group") || input.parentElement;
    if (!group) return;
    group.classList.remove("has-error");
    group.classList.add("has-success");
    input.setAttribute("aria-invalid", "false");
    const msgEl =
      input.getAttribute("aria-describedby") &&
      document.getElementById(input.getAttribute("aria-describedby"));
    if (msgEl) {
      msgEl.textContent = "";
      msgEl.style.display = "none";
    }
  }

  function clearState(input) {
    const group = input.closest(".form-group") || input.parentElement;
    if (!group) return;
    group.classList.remove("has-error", "has-success");
    input.setAttribute("aria-invalid", "false");
    const msgEl =
      input.getAttribute("aria-describedby") &&
      document.getElementById(input.getAttribute("aria-describedby"));
    if (msgEl) {
      msgEl.textContent = "";
      msgEl.style.display = "none";
    }
  }

  function validateInput(input) {
    const value = input.value.trim();

    // Required check
    if (input.required && !value) {
      showError(input, "This field is required");
      return false;
    }

    if (!value) {
      clearState(input);
      return true;
    }

    // URL validation
    if (input.type === "url") {
      try {
        new URL(value);
      } catch {
        showError(input, "Please enter a valid URL");
        return false;
      }
    }

    // Number range validation
    if (input.type === "number") {
      const num = parseFloat(value);
      if (isNaN(num)) {
        showError(input, "Please enter a valid number");
        return false;
      }
      if (input.min !== "" && num < parseFloat(input.min)) {
        showError(input, `Minimum value is ${input.min}`);
        return false;
      }
      if (input.max !== "" && num > parseFloat(input.max)) {
        showError(input, `Maximum value is ${input.max}`);
        return false;
      }
    }

    // Time validation
    if (input.type === "time" && value) {
      if (!/^\d{2}:\d{2}(:\d{2})?$/.test(value)) {
        showError(input, "Please enter a valid time");
        return false;
      }
    }

    showSuccess(input);
    return true;
  }

  function validateAllInputs(form) {
    var inputs = form.querySelectorAll(
      "input[required], input[type='url'], input[type='number'], input[type='time'], select[required]"
    );
    var errorCount = 0;
    inputs.forEach(function (input) {
      if (!validateInput(input)) errorCount++;
    });
    return errorCount;
  }

  function initFormValidation(formOrSelector) {
    const form =
      typeof formOrSelector === "string"
        ? document.querySelector(formOrSelector)
        : formOrSelector || document.querySelector("form");
    if (!form) return;

    const inputs = form.querySelectorAll(
      "input[required], input[type='url'], input[type='number'], input[type='time'], select[required]"
    );

    inputs.forEach(function (input) {
      input.addEventListener("blur", function () {
        validateInput(input);
      });

      input.addEventListener("input", function () {
        // Clear error state as user types
        const group = input.closest(".form-group") || input.parentElement;
        if (group && group.classList.contains("has-error")) {
          clearState(input);
        }
      });
    });

    // Intercept submit to show validation summary
    form.addEventListener("submit", function (e) {
      var errorCount = validateAllInputs(form);
      if (errorCount > 0) {
        e.preventDefault();
        if (typeof showToast === "function") {
          showToast("error", errorCount + (errorCount === 1 ? " error needs" : " errors need") + " fixing before saving.");
        }
        // Visual shake feedback on blocked submit
        form.classList.add("form-shake");
        form.addEventListener("animationend", function handler() {
          form.classList.remove("form-shake");
          form.removeEventListener("animationend", handler);
        });
        // Focus first invalid input
        var firstInvalid = form.querySelector('[aria-invalid="true"]');
        if (firstInvalid) firstInvalid.focus();
      }
    });
  }

  // Auto-initialize on DOMContentLoaded for forms with .settings-form or .validated-form
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".settings-form, .validated-form").forEach(function (form) {
      initFormValidation(form);
    });
  });

  window.FormValidator = {
    initFormValidation: initFormValidation,
    validateInput: validateInput,
    validateAllInputs: validateAllInputs,
  };
})();

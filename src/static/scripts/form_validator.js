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
    // Backwards-compatible shim: older callers only need the count.
    return validateAllInputsDetailed(form).count;
  }

  // Returns the human-facing label for an invalid input, used to build
  // specific validation messages. Lookup order prefers explicit author hints
  // (data-label, aria-label) over DOM-derived labels so we never fall back
  // to an unhelpful titlecased `name` when the author provided a real label.
  function getInputLabel(input) {
    if (!input) return "This field";
    var dataLabel = input.getAttribute("data-label");
    if (dataLabel) return dataLabel.trim();
    var ariaLabel = input.getAttribute("aria-label");
    if (ariaLabel) return ariaLabel.trim();
    var id = input.id;
    if (id) {
      var explicit = document.querySelector('label[for="' + id + '"]');
      if (explicit && explicit.textContent) {
        return explicit.textContent.trim().replace(/\s+/g, " ");
      }
    }
    var wrapping = input.closest("label");
    if (wrapping && wrapping.textContent) {
      return wrapping.textContent.trim().replace(/\s+/g, " ");
    }
    if (input.name) {
      return input.name.charAt(0).toUpperCase() + input.name.slice(1);
    }
    return "This field";
  }

  function classifyInvalid(input) {
    var value = (input.value || "").trim();
    if (input.required && !value) return "required";
    if (input.type === "number" && value) {
      var num = parseFloat(value);
      if (isNaN(num)) return "not_a_number";
      if (input.min !== "" && num < parseFloat(input.min)) return "below_min";
      if (input.max !== "" && num > parseFloat(input.max)) return "above_max";
    }
    if (input.type === "url" && value) return "invalid_url";
    return "invalid";
  }

  function describeReason(input, reason) {
    switch (reason) {
      case "required":
        return " is required";
      case "not_a_number":
        return " must be a number";
      case "below_min":
        return " must be at least " + input.min;
      case "above_max":
        return " must be at most " + input.max;
      case "invalid_url":
        return " must be a valid URL";
      default:
        return " is invalid";
    }
  }

  function validateAllInputsDetailed(form) {
    var inputs = form.querySelectorAll(
      "input[required], input[type='url'], input[type='number'], input[type='time'], textarea[required], select[required]"
    );
    var invalid = [];
    inputs.forEach(function (input) {
      if (!validateInput(input)) {
        var reason = classifyInvalid(input);
        invalid.push({
          input: input,
          label: getInputLabel(input),
          reason: reason,
          message: getInputLabel(input) + describeReason(input, reason),
        });
      }
    });
    return { count: invalid.length, invalid: invalid };
  }

  function buildValidationMessage(result) {
    if (!result || result.count === 0) return "";
    var first = result.invalid[0];
    var base = first.message || first.label + describeReason(first.input, first.reason);
    if (result.count === 1) return base;
    return base + " (and " + (result.count - 1) + " more)";
  }

  function focusFirstInvalid(form) {
    var firstInvalid = form.querySelector('[aria-invalid="true"]');
    if (firstInvalid && typeof firstInvalid.focus === "function") {
      firstInvalid.focus();
      if (typeof firstInvalid.scrollIntoView === "function") {
        try {
          firstInvalid.scrollIntoView({ block: "center", behavior: "smooth" });
        } catch {
          firstInvalid.scrollIntoView();
        }
      }
    }
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
      var result = validateAllInputsDetailed(form);
      if (result.count > 0) {
        e.preventDefault();
        if (typeof showToast === "function") {
          showToast("error", buildValidationMessage(result));
        }
        // Visual shake feedback on blocked submit
        form.classList.add("form-shake");
        form.addEventListener("animationend", function handler() {
          form.classList.remove("form-shake");
          form.removeEventListener("animationend", handler);
        });
        focusFirstInvalid(form);
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
    validateAllInputsDetailed: validateAllInputsDetailed,
    getInputLabel: getInputLabel,
    describeReason: describeReason,
    buildValidationMessage: buildValidationMessage,
    focusFirstInvalid: focusFirstInvalid,
  };
})();

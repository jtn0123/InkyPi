# pyright: reportMissingImports=false
"""Per-plugin minimum-viable form inputs for the Update Preview smoke test.

Each entry maps a plugin id to the happy-path inputs required to make the
``/update_now`` POST succeed end-to-end (plugin ``generate_image`` returns an
image) without requiring external API keys, network round-trips, or file
uploads. Keep payloads tiny — this is a smoke test, not a plugin config harness.

Adding a plugin: drop a new ``"<plugin_id>": { ... }`` entry below. Inputs are
applied in-order; ``fill_form_inputs`` below maps them to ``input``,
``select``, and ``textarea`` elements inside ``#settingsForm``. Plugins that
require API keys, uploads, or network calls should stay out of this dict
until their fixtures can be stubbed in a follow-up.
"""

from __future__ import annotations

# plugin_id -> { form_field_name: value }
#
# Scope is deliberately narrow: three plugins that render offline with no
# external dependencies. Extending coverage is a one-line dict entry once the
# pattern is proven.
PLUGIN_FORM_INPUTS: dict[str, dict[str, str]] = {
    # Clock renders entirely from local settings; no API key required.
    # JTN-681 showed the face-picker handler can silently no-op — this smoke
    # test catches the equivalent regression at the Update Preview level.
    "clock": {
        "selectedClockFace": "Gradient Clock",
        "primaryColor": "#db3246",
        "secondaryColor": "#000000",
    },
    # Year Progress needs no inputs — it computes from the current date.
    "year_progress": {},
    # Todo List renders from optional fields only; empty list is valid input.
    "todo_list": {
        "title": "Smoke test",
        "fontSize": "normal",
        "listStyle": "disc",
    },
    # Countdown exercises text + date inputs, rendered from schema with
    # ``style_settings = True`` so ``populateStyleSettings`` will re-hydrate
    # the form after a page reload (JTN-723 round-trip assertion).
    "countdown": {
        "title": "Vacation",
        "date": "2030-12-31",
    },
}


def fill_form_inputs(page, inputs: dict[str, str]) -> None:
    """Fill ``#settingsForm`` fields from an inputs dict.

    Uses ``page.evaluate`` so the call site stays synchronous with Playwright
    and we can dispatch ``input``/``change`` events the plugin form handlers
    listen for (e.g. the clock face picker's click-driven hidden input).
    """
    if not inputs:
        return
    page.evaluate(
        """
        (values) => {
          const form = document.getElementById('settingsForm');
          if (!form) return;
          for (const [name, value] of Object.entries(values)) {
            const el = form.querySelector(
              `[name="${name}"], #${CSS.escape(name)}`
            );
            if (!el) continue;
            // Native setter so React/Alpine-style frameworks pick up the
            // change (InkyPi is vanilla JS but this keeps the helper portable).
            const proto = Object.getPrototypeOf(el);
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) desc.set.call(el, value); else el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
        """,
        inputs,
    )

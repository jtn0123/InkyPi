# Building InkyPi Plugins

This guide walks you through the process of creating a new plugin for InkyPi.

> **In a hurry?** Jump to the [Hello World walkthrough](#hello-world-walkthrough) at the bottom for a 7-step example you can copy.

> **New to the codebase?** Start with the [architecture overview](architecture.md) to see how plugins fit into the request and refresh flows.

> **Hitting a runtime error?** See [Troubleshooting Plugin Development](troubleshooting.md#plugin-development-troubleshooting) for common failures: API key errors, fetch timeouts, dimension mismatches, memory pressure, screenshot issues, and Jinja2 gotchas.


### 1. Create a Directory for Your Plugin

- Navigate to the `src/plugins` directory.
- Create a new directory named after your plugin. The directory name will be the `id` of your plugin and should be all lowercase with no spaces. Example:

  ```bash
  mkdir plugins/clock
  ```

### 2. Create a Python File and Class for the Plugin

- Inside your new plugin directory, create a Python file with the same name as the directory.
- Define a class in the file that inherits from `BasePlugin`.
- In your new class, implement the `generate_image` function
    - Arguments:
        - `settings`: A dictionary of plugin configuration values from the form inputs in the web UI.
        - `device_config`: An instance of the Config class, used to retrieve device configurations such as display resolution or dotenv keys for any secrets.
    - Images can be generated via the Pillow library or rendered from HTML and CSS file, see [See Generating Images by Rendering HTML and CSS](#generating-images-by-rendering-html-and-css) for details.
    - Return a single `PIL.Image` object to be displayed
    - If there are any issues (e.g., missing configuration options or API keys), raise a `RuntimeError` exception with a clear and concise message to be displayed in the web UI.
- (Optional) Override `generate_settings_template` only to change what the settings page receives. The shared style settings (text colour, background, margins, frame) are shown by default. To hide them, set `style_settings` to `False`:
    ```python
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = False
        return template_params
    ```
    A custom `settings.html` (see [Custom settings templates](#custom-settings-templates)) can also receive extra variables this way.
- (Optional) If your plugin needs to cache or store data across refreshes, you can manage this within the `generate_image` function.
    - For example, you can retrieve and update values as follows:
        ```python
        def generate_image(self, settings, device_config):
            # retrieve stored value with a default
            cached_index = settings.get("index", 0)

            # update value for next refresh
            settings["index"] = settings["index"] + 1
        ```
- (Optional) If your plugin sometimes has nothing worth showing, implement `skip_display_condition` to yield its playlist turn instead of rendering an empty frame. On an e-ink panel the cheapest refresh is the one that never happens.
    - Return `None` to render normally, or a short reason string to skip this cycle. The reason is recorded against the plugin, so a skip reads as deliberate rather than as a silent failure.
    - Intended for plugins with legitimate quiet periods — a scoreboard out of season, a calendar with no events today, a feed with nothing new.
    - Only playlist refreshes are skipped. A manual **Update Now** always renders, because declining an explicit request looks like a broken button.
    - If the hook fetches data to decide and then returns `None`, cache what it fetched in a plugin-private `settings` key so `generate_image` does not immediately repeat the request.

        ```python
        def skip_display_condition(self, settings, device_config, current_dt):
            games = fetch_games(settings, current_dt)
            if not games:
                return "No games to display"

            # Reuse this in generate_image instead of fetching twice.
            settings["_scoreboard_games_cache"] = games
            return None
        ```

- (Optional) `generate_image` may return `None` when your plugin has no image to show at all — it exists for its side effect, such as driving a servo or calling a webhook. The refresh completes and the display is left untouched.
    - This is different from `skip_display_condition`: returning `None` means *"I was never about showing anything"*, while a skip means *"I normally show something, just not this cycle"*.

### 3. Describe the Settings Form (Optional)

Every built-in plugin with options describes its form in Python, with `build_settings_schema`. The shared settings page then renders the form, fills in saved values when you edit an instance, and checks required fields. You don't write HTML or JavaScript for it.

```python
from plugins.base_plugin.settings_schema import field, option, row, schema, section


class Countdown(BasePlugin):
    # The built-in Countdown form, plus a "Count in" dropdown.
    def build_settings_schema(self):
        return schema(
            section(
                "Countdown",
                row(
                    field("title", label="Title", placeholder="e.g. Vacation", required=True),
                    field("date", "date", label="Target Date"),
                ),
                field(
                    "units",
                    "select",
                    label="Count in",
                    default="days",
                    options=[option("days", "Days"), option("weeks", "Weeks")],
                ),
            )
        )
```

Each field's `name` becomes a key in the `settings` dict passed to `generate_image`. Form values arrive as strings, so convert numbers and checkboxes yourself.

**Building blocks** (all in `plugins/base_plugin/settings_schema.py`):

| Helper | Use |
|---|---|
| `schema(*sections)` | The whole form. Return this from `build_settings_schema`. |
| `section(title, *items, description=...)` | A titled card on the settings page. |
| `row(*items)` | Puts fields side by side. |
| `field(name, type="text", label=..., **options)` | One input. See the types and options below. |
| `option(value, label)` / `option_group(label, *options)` | Choices for `select` and `radio_segment` fields. |
| `callout(text, tone="info" or "warning", title=...)` | A note or warning box inside a section. |
| `widget(widget_type, template=..., config=...)` | Embeds a custom partial template for controls the field types can't express (the map picker in Weather, for example). Rarely needed. |

**Field types:**
- `checkbox`: a toggle. A ticked box sends `"true"`. An unticked box sends nothing unless you pass `submit_unchecked=True`, which makes it send `"false"`. Use `submit_unchecked=True` whenever `default="true"`; otherwise unticking isn't saved and the box comes back ticked. Read the value as `settings.get("name") == "true"`. `checked_value` and `unchecked_value` change the strings sent.
- `select` and `radio_segment`: take `options=[...]`.
- `textarea`: takes `rows`.
- `color`: a colour picker.
- `hidden`
- Anything else is a plain `<input>` of that HTML type, such as `text`, `number`, `date`, `time` or `url`.

**Common options:**
- `label`, `default`, `placeholder` and `hint` (small help text under the field).
- `required=True`: the save is refused while the field is empty.
- `min`, `max`, `step` and `pattern`.
- `visible_if={"field": "mode", "equals": "custom"}`: shows the field only while another field has that value. `operator` can also be `not_equals`, `not_empty`, or `in` with `values=[...]`.

#### Reject bad settings when they are saved

Override `validate_settings` to check values before they are stored. Return a short message to refuse the save; the message is shown to the user. Return `None` to accept it. It runs when settings are saved: adding a plugin to a playlist, editing an instance, or saving plugin settings. It runs after the `required=True` check.

```python
from datetime import date


def validate_settings(self, settings):
    raw = settings.get("date")
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        return "Date is required."
    try:
        date.fromisoformat(value)
    except ValueError:
        return f"Invalid date: {value!r} (expected YYYY-MM-DD)"
    return None
```

Return a message rather than raising. An exception is treated as "validation unavailable", and nothing is saved.

Catching bad input here means the user sees the problem straight away, instead of a failed render on the display hours later. `generate_image` should still cope with missing or odd values, because a preview or an older saved instance may not have been validated.

[`countdown`](../src/plugins/countdown/countdown.py) is a small complete example of both hooks. [`weather`](../src/plugins/weather/weather.py) and [`calendar`](../src/plugins/calendar/calendar.py) show larger forms with conditional fields.

A plugin with no options can skip `build_settings_schema`. Its settings page then shows only the shared style settings.

### 4. Add an Icon for Your Plugin

- Create an `icon.png` file in your plugin’s directory. This will be the icon displayed in the web UI.
    - Ensure the icon visually matches the style of existing icons in the project.

### 5. Register Your Plugin

- Create a `plugin-info.json` in your plugin folder
- Add an object for your plugin using the following structure:
    ```json
    {
        "display_name": "Clock",
        "id": "clock",
        "class": "Clock",
        "api_version": "1.0",
        "version": "1.0.0",
        "repository": ""
    }
    ```
    - `display_name`: the name shown in the web UI.
    - `id`: a unique identifier, matching the folder name (lowercase, no spaces).
    - `class`: the name of your plugin's Python class.
    - `api_version`: the plugin API it was written for. The loader warns when its major version doesn't match.
    - `version`: your plugin's own version.
    - `repository`: the GitHub URL, if it is published as a third-party plugin.
- A folder is recognised as a plugin when it contains a `plugin-info.json`.

## Test Your Plugin

- Restart the InkyPi service by running
    ```bash
    sudo systemctl restart inkypi.service
    ```
- Test and ensure that your plugin:
    - Loads correctly on service start.
    - Appears under the "Plugins" section in the web UI with its icon.
    - Generates images for different display sizes and orientations.
    - The settings form renders, and saving bad input shows your `validate_settings` message.
    - Generates and displays images with immediate updates and in a playlist.
    - Editing an existing playlist instance shows its saved values, and saving updates them.

To check the image without a Pi or the web UI, render it straight to a PNG:

```bash
python scripts/dry_run_plugin.py --plugin my_plugin --config settings.json --output out.png
```

If the plugin calls an API, add `--record fixtures/` once, then use `--replay fixtures/` while you iterate on the layout. Replay serves the saved responses, so it uses no network and no API quota.

## Example Directory Structure

Here’s how your plugin directory should look:

```
plugins/{plugin_id}/
    ├── {plugin_id}.py          # Main plugin script
    ├── plugin-info.json        # Plugin manifest file
    ├── icon.png                # Plugin icon
    ├── settings.html           # Rarely needed: custom settings form (prefer build_settings_schema)
    ├── render/                 # Optional: If generating images from html and css files, store them here
    └── {other files/resources} # Any additional files or resources used by the plugin
```

## Custom settings templates

Use a hand-written `settings.html` only when a form really can't be expressed with `build_settings_schema`; no built-in plugin needs one today. If `build_settings_schema` returns a schema, it is used and `settings.html` is ignored.

- Name each input after the settings key it sets (`name="..."`). Those names become the keys of the `settings` dict.
- Match the markup and classes of the shared settings page so the form looks consistent.
- Schema forms are filled in automatically when you edit an instance. A custom template has to do it itself: check `loadPluginSettings` (true in edit mode) and read the saved values from `pluginSettings`:
    ```javascript
    document.addEventListener("DOMContentLoaded", () => {
        if (loadPluginSettings) {
            // Text input
            document.getElementById("message").value = pluginSettings.message || "";

            // Radio
            document.querySelector(`input[name="mode"][value="${pluginSettings.mode}"]`).checked = true;
        }
    });
    ```

## Generating Images by Rendering HTML and CSS

For more complex plugins or dashboards that display dynamic content, you can generate images from HTML and CSS files.

### Using `render_image`
You can generate an image by calling the `BasePlugin`'s `render_image` function, which accepts the following arguments:
- `dimensions` (tuple)                  The width and height of the generated image.
- `html_file` (str)                     Name of the HTML file to render, located in the `render/` directory.
- `css_file` (str, optional)            Name of the CSS file in the `render/` directory.
- `template_params`(dict, optional)     A dictionary of values to be passed into the Jinja template.

### Defining HTML and CSS files
- Place your HTML and CSS files in the `render/` subdirectory, as `render_image` looks for them there.
- Your HTML file should extend `BasePlugin`'s `plugin.html` and define its content like this:
```
{% extends "plugin.html" %}

{% block content %}
<!-- Your content here -->
{% endblock %}
```
- The `plugin.html` base template includes all font faces found in the `static/fonts/` directory, making them available for use in your templates
- The base template also handles style options such as text color, background image or color, margin and frame settings. To apply these styles, pass the `settings` parameter from the `generate_image` function as part of template_params argument with the `plugin_settings` key.

For reference, see the Weather and AI Text plugins.

### Behind the Scenes
1. The `render_image` function renders the HTML template using the Jinja2 library.
2. It then calls the `take_screenshot_html` function in `image_utils.py`.
3. This function uses the Chromium Browser in headless mode to load the HTML file and capture a screenshot.


## Publishing a third-party plugin

To publish your plugin as a third-party plugin for others to install, you'll need to create a new repository. See [Creating a new repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository) in the GitHub documentation.

Note: It’s recommended to name your repository `InkyPi-{plugin_name}` so it’s easy to discover via GitHub search.

### Repository Structure

Your repository must include:

- **A folder named after your `plugin_id`**
  - This folder will contain your plugin source code, see [example directory structure](./building_plugins.md#example-directory-structure) for the contents of the folder.
  - When a user installs your plugin, this folder is copied into the `src/plugins/` directory.

- **A README file** containing:
  - A short, clear, one-sentence description of what the plugin does.
  - At least one high-quality screenshot showing the plugin running.
  - Any external APIs the plugin depends on, including:
    - Links to the API documentation.
    - Instructions for obtaining and configuring API keys, if required.
    - Whether the API requires a key and any known usage limits or costs (for example, free tiers or rate limits).
  - The current development status (for example: actively maintained, work in progress, looking for a maintainer, or no longer maintained).

---

See [InkyPi-Plugin-Template](https://github.com/fatihak/InkyPi-Plugin-Template) for a sample template of a third-party plugin.

Once you're done, feel free to add your plugin to the [3rd Party Plugin List](https://github.com/fatihak/InkyPi/wiki/3rd-Party-Plugins) and share it in the [🙌 Show and Tell Discussion Board](https://github.com/fatihak/InkyPi/discussions/categories/show-and-tell).

---

## Hello World walkthrough

The fastest way to understand the plugin system is to build the smallest possible plugin and watch it appear in the web UI. This walkthrough creates a plugin that draws a message on the display, with a one-field settings form, in seven steps.

### 1. Create the plugin directory

```bash
mkdir src/plugins/hello
```

The directory name (`hello`) becomes the plugin's `id` — lowercase, no spaces.

### 2. Add the plugin metadata

Create `src/plugins/hello/plugin-info.json`:

```json
{
  "display_name": "Hello World",
  "id": "hello",
  "class": "Hello",
  "api_version": "1.0",
  "version": "1.0.0"
}
```

`api_version` and `version` are checked at load time — see [JTN-300](https://linear.app/jtn0123/issue/JTN-300).

### 3. Implement the plugin class

Create `src/plugins/hello/hello.py`:

```python
import logging

from PIL import Image, ImageDraw

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import field, schema, section
from utils.app_utils import get_font

logger = logging.getLogger(__name__)


class Hello(BasePlugin):
    def build_settings_schema(self):
        return schema(
            section(
                "Hello World",
                field(
                    "message",
                    label="Message",
                    default="Hello, World!",
                    placeholder="Hello, World!",
                    required=True,
                ),
            )
        )

    def validate_settings(self, settings):
        message = settings.get("message")
        if isinstance(message, str) and len(message) > 60:
            return "Keep the message under 60 characters so it fits on one line."
        return None

    def generate_image(self, settings, device_config):
        dimensions = self.get_oriented_dimensions(device_config)
        width, height = dimensions

        image = Image.new("RGB", dimensions, (255, 255, 255))
        draw = ImageDraw.Draw(image)

        message = settings.get("message", "Hello, World!")
        font = get_font("Jost", font_size=int(width * 0.08))

        draw.text(
            (width / 2, height / 2),
            message,
            anchor="mm",
            fill=(0, 0, 0),
            font=font,
        )
        return image
```

The class name (`Hello`) must match the `class` field in `plugin-info.json`.

### 4. Check the settings form

There is no template to write: `build_settings_schema` above gives the plugin a **Message** field, and `validate_settings` refuses messages that won't fit. The field's name (`message`) becomes the key in the `settings` dict passed to `generate_image()`. See [Describe the Settings Form](#3-describe-the-settings-form-optional) for the other field types.

### 5. Add an icon

Drop any 256x256 PNG into `src/plugins/hello/icon.png`. The web UI shows it in the plugin picker.

### 6. Run the dev server

```bash
INKYPI_ENV=dev .venv/bin/python src/inkypi.py --dev --web-only
```

Or use the [Docker setup](development.md#docker-development) added in JTN-297:

```bash
docker compose up --build
```

### 7. Verify in the web UI

1. Open http://localhost:8080
2. Click **Add Plugin** on the dashboard or playlist page
3. Find **Hello World** in the list
4. Save it to a playlist with any message
5. The next refresh tick will show the message on the (mock) display

That's it — you've built and shipped a plugin. From here, look at the [`year_progress`](../src/plugins/year_progress/) plugin for a slightly richer example using `render_image()` with HTML/CSS templates, or [`weather`](../src/plugins/weather/) for a plugin that calls an external API.

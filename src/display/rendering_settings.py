"""Names of the screen-rendering settings.

Kept apart from ``display.crisp`` so the web app and the display manager can
read them at startup without importing numpy; the conversion code is only
loaded when a frame is actually converted.
"""

# A plugin opts its frames in by listing this in plugin-info.json
# "image_settings"; that list already travels with every display push.
CRISP_IMAGE_SETTING = "crisp"
# Device setting (in config "image_settings"): "auto" converts frames from
# opted-in plugins crisply, "dithered" leaves every frame to the driver.
SCREEN_RENDERING_KEY = "screen_rendering"
SCREEN_RENDERING_MODES = ("auto", "dithered")

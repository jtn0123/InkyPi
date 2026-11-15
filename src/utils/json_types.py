"""A name for decoded JSON objects.

``device.json``, plugin settings, playlist entries and request bodies reach the
code as dicts whose values are only known after a check. ``JsonObject`` says
that in a signature, where a bare ``dict[str, Any]`` could mean anything.

The packages mypy runs with ``disallow_any_explicit`` (see ``mypy.ini``) must
use this name, or a real type, instead of writing ``Any`` themselves.
"""

from typing import Any

#: A decoded JSON object: string keys, values not yet checked.
JsonObject = dict[str, Any]

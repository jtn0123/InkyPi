from __future__ import annotations

from typing import Any


def option(value: Any, label: str, **kwargs: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"value": value, "label": label}
    data.update(kwargs)
    return data


def option_group(label, *options):
    return {"kind": "option_group", "label": label, "options": list(options)}


def field(name, field_type="text", label=None, **kwargs):
    data = {
        "kind": "field",
        "type": field_type,
        "name": name,
        "label": label or name,
    }
    data.update(kwargs)
    return data


def row(*items, **kwargs):
    data = {"kind": "row", "items": list(items)}
    data.update(kwargs)
    return data


def callout(text, tone="info", icon="info", title=None, **kwargs):
    data = {
        "kind": "callout",
        "text": text,
        "tone": tone,
        "icon": icon,
    }
    if title:
        data["title"] = title
    data.update(kwargs)
    return data


def widget(widget_type, **kwargs):
    data = {"kind": "widget", "widget_type": widget_type}
    data.update(kwargs)
    return data


def section(title, *items, **kwargs):
    data = {"title": title, "items": list(items)}
    data.update(kwargs)
    return data


def schema(*sections, **kwargs):
    data = {"version": 1, "sections": list(sections)}
    data.update(kwargs)
    return data

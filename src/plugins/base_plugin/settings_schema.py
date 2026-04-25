from __future__ import annotations

from typing import Any


def option(value: Any, label: str, **kwargs: Any) -> dict[str, object]:
    data: dict[str, object] = {"value": value, "label": label}
    data.update(kwargs)
    return data


def option_group(label: str, *options: dict[str, object]) -> dict[str, object]:
    data: dict[str, object] = {
        "kind": "option_group",
        "label": label,
        "options": list(options),
    }
    return data


def field(
    name: str,
    field_type: str = "text",
    label: str | None = None,
    **kwargs: Any,
) -> dict[str, object]:
    data: dict[str, object] = {
        "kind": "field",
        "type": field_type,
        "name": name,
        "label": label or name,
    }
    data.update(kwargs)
    return data


def row(*items: dict[str, object], **kwargs: Any) -> dict[str, object]:
    data: dict[str, object] = {"kind": "row", "items": list(items)}
    data.update(kwargs)
    return data


def callout(
    text: str,
    tone: str = "info",
    icon: str = "info",
    title: str | None = None,
    **kwargs: Any,
) -> dict[str, object]:
    data: dict[str, object] = {
        "kind": "callout",
        "text": text,
        "tone": tone,
        "icon": icon,
    }
    if title:
        data["title"] = title
    data.update(kwargs)
    return data


def widget(widget_type: str, **kwargs: Any) -> dict[str, object]:
    data: dict[str, object] = {"kind": "widget", "widget_type": widget_type}
    data.update(kwargs)
    return data


def section(title: str, *items: dict[str, object], **kwargs: Any) -> dict[str, object]:
    data: dict[str, object] = {"title": title, "items": list(items)}
    data.update(kwargs)
    return data


def schema(*sections: dict[str, object], **kwargs: Any) -> dict[str, object]:
    data: dict[str, object] = {"version": 1, "sections": list(sections)}
    data.update(kwargs)
    return data

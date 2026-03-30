# pyright: reportMissingImports=false
import pytest
from PIL import Image


@pytest.fixture()
def plugin_config():
    return {"id": "todo_list", "class": "TodoList", "name": "Todo List"}


def test_todo_list_basic(plugin_config, device_config_dev):
    from plugins.todo_list.todo_list import TodoList

    p = TodoList(plugin_config)
    result = p.generate_image(
        {
            "title": "Tasks",
            "list-title[]": ["Shopping"],
            "list[]": ["Milk\nEggs\nBread"],
            "listStyle": "disc",
            "fontSize": "normal",
        },
        device_config_dev,
    )
    assert isinstance(result, Image.Image)


def test_todo_list_multiple_lists(plugin_config, device_config_dev):
    from plugins.todo_list.todo_list import TodoList

    p = TodoList(plugin_config)
    result = p.generate_image(
        {
            "title": "My Lists",
            "list-title[]": ["Work", "Home"],
            "list[]": ["Task A\nTask B", "Clean\nCook"],
            "listStyle": "square",
            "fontSize": "normal",
        },
        device_config_dev,
    )
    assert isinstance(result, Image.Image)


def test_todo_list_empty_items_filtered(plugin_config, device_config_dev):
    from plugins.todo_list.todo_list import TodoList

    p = TodoList(plugin_config)
    result = p.generate_image(
        {
            "title": "Sparse",
            "list-title[]": ["Items"],
            "list[]": ["A\n\n\nB\n  \nC"],
            "listStyle": "disc",
            "fontSize": "normal",
        },
        device_config_dev,
    )
    assert isinstance(result, Image.Image)


def test_todo_list_font_sizes(plugin_config, device_config_dev):
    from plugins.todo_list.todo_list import FONT_SIZES, TodoList

    for size_name in FONT_SIZES:
        p = TodoList(plugin_config)
        result = p.generate_image(
            {
                "title": f"Size {size_name}",
                "list-title[]": ["Items"],
                "list[]": ["Item 1"],
                "listStyle": "disc",
                "fontSize": size_name,
            },
            device_config_dev,
        )
        assert isinstance(result, Image.Image)


def test_todo_list_vertical(plugin_config, device_config_dev):
    from plugins.todo_list.todo_list import TodoList

    device_config_dev.update_value("orientation", "vertical")

    p = TodoList(plugin_config)
    result = p.generate_image(
        {
            "title": "Vertical",
            "list-title[]": ["Items"],
            "list[]": ["Item 1\nItem 2"],
            "listStyle": "disc",
            "fontSize": "normal",
        },
        device_config_dev,
    )
    assert isinstance(result, Image.Image)

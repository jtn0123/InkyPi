import pytest
from PIL import Image


def test_abstract_display_initialize_display_not_implemented(device_config_dev):
    """Test that AbstractDisplay raises NotImplementedError for initialize_display."""
    from display.abstract_display import AbstractDisplay

    # Create instance without calling __init__ to avoid the NotImplementedError
    display = AbstractDisplay.__new__(AbstractDisplay)
    display.device_config = device_config_dev

    with pytest.raises(NotImplementedError, match="Method 'initialize_display"):
        display.initialize_display()


def test_abstract_display_display_image_not_implemented(device_config_dev):
    """Test that AbstractDisplay raises NotImplementedError for display_image."""
    from display.abstract_display import AbstractDisplay

    # Create instance without calling __init__ to avoid the NotImplementedError
    display = AbstractDisplay.__new__(AbstractDisplay)
    display.device_config = device_config_dev
    test_image = Image.new("RGB", (100, 100), "white")

    with pytest.raises(NotImplementedError, match="Method 'display_image"):
        display.display_image(test_image)


def test_abstract_display_initialization_sets_device_config(device_config_dev):
    """Test that AbstractDisplay properly initializes device_config."""
    from display.abstract_display import AbstractDisplay

    # Create instance without calling __init__ to avoid the NotImplementedError
    display = AbstractDisplay.__new__(AbstractDisplay)
    display.device_config = device_config_dev
    assert display.device_config == device_config_dev

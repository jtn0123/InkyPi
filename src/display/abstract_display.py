from typing import Protocol

from PIL import Image


class DeviceConfigLike(Protocol):
    """Subset of config methods/fields used by display backends."""

    def get_config(self, key: str, default: object = ...) -> object: ...

    def update_value(self, key: str, value: object, write: bool = ...) -> None: ...

    def get_resolution(self) -> tuple[int, int]: ...

    BASE_DIR: str
    current_image_file: str
    processed_image_file: str
    history_image_dir: str


class AbstractDisplay:
    """
    Abstract base class for all display devices.

    This class defines methods that subclasses are required to implement for
    initialization and to display images on a screen.

    These implementations will be device specific.
    """

    def __init__(self, device_config: DeviceConfigLike) -> None:
        """
        Initializes the display manager with the provided device configuration.

        Args:
            device_config (object): Configuration object for the display device.
        """
        self.device_config: DeviceConfigLike = device_config
        self.initialize_display()

    def initialize_display(self) -> None:
        """
        Abstract method to initialize the display hardware.

        This method must be implemented by subclasses to set up the display
        device properly.

        Raises:
            NotImplementedError: If not implemented in a subclass.
        """
        raise NotImplementedError(
            "Method 'initialize_display(...) must be provided in a subclass."
        )

    def display_image(
        self, image: Image.Image, image_settings: list[object] | None = None
    ) -> None:
        """
        Abstract method to display an image on the screen.  Implementations of this
        method should handle the device specific operations.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): List of settings to modify how the image is displayed.

        Raises:
            NotImplementedError: If not implemented in a subclass.
        """
        if image_settings is None:
            image_settings = []
        raise NotImplementedError(
            "Method 'display_image(...) must be provided in a subclass."
        )

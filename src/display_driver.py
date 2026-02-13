"""Waveshare 7.5" V2 ePaper display driver."""

import logging
from typing import TYPE_CHECKING

from PIL import Image

logger = logging.getLogger(__name__)

# Display dimensions
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

# Try to import Waveshare library (only available on Raspberry Pi)
try:
    from lib.waveshare_epd import epd7in5_V2

    WAVESHARE_AVAILABLE = True
except (ImportError, RuntimeError, OSError):
    WAVESHARE_AVAILABLE = False
    epd7in5_V2 = None


class DisplayDriver:
    """Driver for Waveshare 7.5" V2 ePaper display."""

    def __init__(self, rotation: int = 0):
        """Initialize display driver.

        Args:
            rotation: Display rotation in degrees (0, 90, 180, 270).
        """
        self.rotation = rotation
        self.epd = None
        self._initialized = False

    @property
    def is_available(self) -> bool:
        """Check if the display hardware is available."""
        return WAVESHARE_AVAILABLE

    def init(self) -> bool:
        """Initialize the ePaper display.

        Returns:
            True if initialization successful, False otherwise.
        """
        if not WAVESHARE_AVAILABLE:
            logger.warning("Waveshare library not available - running in preview mode")
            return False

        try:
            self.epd = epd7in5_V2.EPD()
            self.epd.init()
            self._initialized = True
            logger.info("ePaper display initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ePaper display: {e}")
            return False

    def clear(self) -> None:
        """Clear the display to white."""
        if not self._initialized or self.epd is None:
            logger.warning("Display not initialized, skipping clear")
            return

        try:
            self.epd.Clear()
            logger.info("Display cleared")
        except Exception as e:
            logger.error(f"Failed to clear display: {e}")

    def display(self, image: Image.Image) -> None:
        """Display an image on the ePaper.

        Args:
            image: PIL Image to display (should be 800x480, mode "1").
        """
        if not self._initialized or self.epd is None:
            logger.warning("Display not initialized, skipping display")
            return

        # Apply rotation if needed
        if self.rotation != 0:
            image = image.rotate(self.rotation, expand=True)

        # Ensure correct size
        if image.size != (DISPLAY_WIDTH, DISPLAY_HEIGHT):
            logger.warning(
                f"Image size {image.size} doesn't match display "
                f"({DISPLAY_WIDTH}x{DISPLAY_HEIGHT}), resizing"
            )
            image = image.resize((DISPLAY_WIDTH, DISPLAY_HEIGHT))

        # Ensure 1-bit mode
        if image.mode != "1":
            image = image.convert("1")

        try:
            self.epd.display(self.epd.getbuffer(image))
            logger.info("Image displayed successfully")
        except Exception as e:
            logger.error(f"Failed to display image: {e}")

    def sleep(self) -> None:
        """Put the display into sleep mode to save power."""
        if not self._initialized or self.epd is None:
            return

        try:
            self.epd.sleep()
            logger.info("Display entering sleep mode")
        except Exception as e:
            logger.error(f"Failed to put display to sleep: {e}")

    def cleanup(self) -> None:
        """Clean up display resources."""
        if self.epd is not None:
            try:
                from lib.waveshare_epd import epdconfig
                epdconfig.module_exit()
                logger.info("Display resources cleaned up")
            except Exception as e:
                logger.error(f"Failed to cleanup display: {e}")

        self._initialized = False
        self.epd = None


class MockDisplayDriver(DisplayDriver):
    """Mock display driver for testing without hardware."""

    def __init__(self, rotation: int = 0):
        """Initialize mock display driver."""
        super().__init__(rotation)
        self._last_image: Image.Image | None = None

    @property
    def is_available(self) -> bool:
        """Mock is always available."""
        return True

    def init(self) -> bool:
        """Mock initialization always succeeds."""
        self._initialized = True
        logger.info("Mock display initialized")
        return True

    def clear(self) -> None:
        """Mock clear."""
        logger.info("Mock display cleared")

    def display(self, image: Image.Image) -> None:
        """Store image for inspection."""
        self._last_image = image
        logger.info(f"Mock display showing image: {image.size}, mode={image.mode}")

    def sleep(self) -> None:
        """Mock sleep."""
        logger.info("Mock display sleeping")

    def cleanup(self) -> None:
        """Mock cleanup."""
        self._initialized = False
        logger.info("Mock display cleaned up")

    @property
    def last_image(self) -> Image.Image | None:
        """Get the last displayed image."""
        return self._last_image


def get_display_driver(rotation: int = 0, force_mock: bool = False) -> DisplayDriver:
    """Get appropriate display driver based on environment.

    Args:
        rotation: Display rotation in degrees.
        force_mock: Force use of mock driver even if hardware is available.

    Returns:
        DisplayDriver instance.
    """
    if force_mock or not WAVESHARE_AVAILABLE:
        return MockDisplayDriver(rotation)
    return DisplayDriver(rotation)

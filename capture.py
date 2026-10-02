"""Screenshot engine using PIL ImageGrab (wraps macOS screencapture).

CGWindowListCreateImage was deprecated in macOS 14+ and frequently returns only
the desktop wallpaper for GPU-accelerated apps (browsers, native poker clients).
ImageGrab on macOS shells out to /usr/sbin/screencapture, which uses the modern
ScreenCaptureKit pipeline and captures every visible app correctly.
"""

from __future__ import annotations

from PIL import Image, ImageGrab
import log

L = log.get("capture")


def capture_region_pil(region: dict) -> Image.Image | None:
    """Capture a screen region (global coords) and return as PIL Image."""
    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
    bbox = (x, y, x + w, y + h)
    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return img.convert("RGB")
    except Exception as e:
        L.warning(f"ImageGrab failed for {region}: {e}")
        return None

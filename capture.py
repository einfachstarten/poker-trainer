"""Screenshot engine using macOS Quartz API (no disk I/O)."""

from __future__ import annotations

import numpy as np
from PIL import Image
from Quartz import (
    CGRectMake,
    CGWindowListCreateImage,
    kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID,
    kCGWindowImageDefault,
)
from Quartz.CoreGraphics import (
    CGImageGetWidth,
    CGImageGetHeight,
    CGImageGetBytesPerRow,
    CGDataProviderCopyData,
    CGImageGetDataProvider,
)
import log

L = log.get("capture")


def capture_region(region: dict) -> np.ndarray | None:
    """Capture a screen region directly into a numpy array."""
    rect = CGRectMake(region["x"], region["y"], region["w"], region["h"])
    cg_image = CGWindowListCreateImage(
        rect,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
        kCGWindowImageDefault,
    )
    if cg_image is None:
        L.warning(f"CGWindowListCreateImage returned None for {region}")
        return None

    width = CGImageGetWidth(cg_image)
    height = CGImageGetHeight(cg_image)
    bytes_per_row = CGImageGetBytesPerRow(cg_image)
    data = CGDataProviderCopyData(CGImageGetDataProvider(cg_image))

    arr = np.frombuffer(data, dtype=np.uint8)
    arr = arr.reshape((height, bytes_per_row // 4, 4))
    arr = arr[:height, :width, :]
    return arr


def capture_region_pil(region: dict) -> Image.Image | None:
    """Capture a screen region and return as PIL Image."""
    arr = capture_region(region)
    if arr is None:
        return None
    rgb = arr[:, :, [2, 1, 0]]
    return Image.fromarray(rgb)

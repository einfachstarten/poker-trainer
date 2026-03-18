"""Change detection between consecutive frames."""

from __future__ import annotations

import numpy as np
import log

L = log.get("detector")


class ChangeDetector:
    def __init__(self, threshold: float = 0.05):
        self.threshold = threshold
        self.prev_frame: np.ndarray | None = None
        L.info(f"Initialisiert mit threshold={threshold}")

    def has_changed(self, frame: np.ndarray) -> bool:
        """Compare frame against previous. Returns True if significant change."""
        if self.prev_frame is None:
            self.prev_frame = frame
            L.debug("Erster Frame → trigger")
            return True

        if frame.shape != self.prev_frame.shape:
            L.warning(f"Shape geändert: {self.prev_frame.shape} → {frame.shape}")
            self.prev_frame = frame
            return True

        f1 = self.prev_frame[::2, ::2, :3].astype(np.int16)
        f2 = frame[::2, ::2, :3].astype(np.int16)
        diff = np.abs(f2 - f1)

        changed_pixels = np.any(diff > 30, axis=2)
        change_ratio = float(np.mean(changed_pixels))

        self.prev_frame = frame
        changed = change_ratio > self.threshold
        if changed:
            L.debug(f"Change ratio: {change_ratio:.3f} > {self.threshold} → TRIGGER")
        return changed

    def reset(self):
        self.prev_frame = None
        L.debug("Reset")

"""Keeps an eye on the table: captures continuously and hands over a frame when something changed.

Reading a frame costs an LLM call, so the watcher is frugal. It waits until the picture has
settled, reads quickly when the bottom strip changed (where the action buttons appear, the
player is probably on turn) and rarely when only the rest of the table changed.
"""

from __future__ import annotations

import threading
import time

import numpy as np

import capture
import log
from detector import ChangeDetector

L = log.get("watcher")


class Watcher:
    def __init__(self, get_region, on_frame, interval: float = 0.3, settle: float = 0.4,
                 max_wait: float = 2.0, turn_gap: float = 1.0, table_gap: float = 6.0,
                 threshold: float = 0.003, buttons_zone: float = 0.18):
        """on_frame(img, reason) runs in the watcher thread and should return quickly;
        reason is 'buttons', 'table' or 'forced'."""
        self._get_region = get_region
        self._on_frame = on_frame
        self._interval = interval
        self._settle = settle
        self._max_wait = max_wait
        self._gaps = {"buttons": turn_gap, "table": table_gap}
        self._zone = buttons_zone
        self._table = ChangeDetector(threshold)
        self._buttons = ChangeDetector(threshold * 3)
        self._running = False
        self._force = threading.Event()
        self._thread: threading.Thread | None = None
        self.reads = 0

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        L.info("Watcher gestartet")

    def stop(self):
        self._running = False
        self._force.set()

    def force(self):
        """Read the table now, whatever the change detection says (F1)."""
        self._force.set()

    def _loop(self):
        dirty: dict[str, float] = {}  # reason → time of first unread change
        last_change = 0.0
        last_emit = 0.0
        while self._running:
            self._force.wait(self._interval)
            if not self._running:
                break
            forced = self._force.is_set()
            self._force.clear()

            img = capture.capture_region_pil(self._get_region())
            if img is None:
                continue
            frame = np.asarray(img)
            split = int(frame.shape[0] * (1 - self._zone))
            now = time.time()
            if self._buttons.has_changed(frame[split:]):
                dirty.setdefault("buttons", now)
                last_change = now
            if self._table.has_changed(frame[:split]):
                dirty.setdefault("table", now)
                last_change = now

            reason = None
            if forced:
                reason = "forced"
            elif dirty:
                settled = now - last_change >= self._settle
                overdue = now - min(dirty.values()) >= self._max_wait
                candidate = "buttons" if "buttons" in dirty else "table"
                if (settled or overdue) and now - last_emit >= self._gaps[candidate]:
                    reason = candidate
            if not reason:
                continue

            dirty.clear()
            last_emit = time.time()
            self.reads += 1
            try:
                self._on_frame(img, reason)
            except Exception as e:  # a failed read must not kill the watcher
                L.error(f"Frame-Verarbeitung fehlgeschlagen: {e}")
        L.info(f"Watcher gestoppt nach {self.reads} Lesungen")

"""Split screen: table window on the left, companion panel on the right.

Screen coordinates come in two flavours here. Quartz (capture region, window list,
Accessibility) has its origin at the top left of the primary screen, Cocoa (NSWindow,
NSScreen) at the bottom left.
"""

from __future__ import annotations

import os

import log
from AppKit import NSScreen
from ApplicationServices import (
    AXIsProcessTrusted, AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
    AXUIElementSetAttributeValue, AXValueCreate, AXValueGetValue,
    kAXValueCGPointType, kAXValueCGSizeType,
)
from Quartz import (
    CGPoint, CGSize, CGWindowListCopyWindowInfo, kCGNullWindowID,
    kCGWindowListOptionOnScreenOnly, kCGWindowListExcludeDesktopElements,
)

L = log.get("layout")

PANEL_SHARE = 0.28
PANEL_MIN_W, PANEL_MAX_W = 380, 520


def _primary_height() -> float:
    return NSScreen.screens()[0].frame().size.height


def _screen_for(region: dict):
    """The screen that holds the centre of a Quartz region."""
    cx = region["x"] + region["w"] / 2
    cy = _primary_height() - (region["y"] + region["h"] / 2)
    for screen in NSScreen.screens():
        f = screen.frame()
        if f.origin.x <= cx < f.origin.x + f.size.width and f.origin.y <= cy < f.origin.y + f.size.height:
            return screen
    return NSScreen.mainScreen()


def split_frames(region: dict) -> tuple[dict, dict]:
    """(panel window frame in Cocoa coords, table area in Quartz coords) on the region's screen."""
    visible = _screen_for(region).visibleFrame()
    panel_w = int(max(PANEL_MIN_W, min(PANEL_MAX_W, visible.size.width * PANEL_SHARE)))
    panel = {"x": int(visible.origin.x + visible.size.width - panel_w), "y": int(visible.origin.y),
             "w": panel_w, "h": int(visible.size.height)}
    table = {"x": int(visible.origin.x),
             "y": int(_primary_height() - visible.origin.y - visible.size.height),
             "w": int(visible.size.width - panel_w), "h": int(visible.size.height)}
    return panel, table


def map_region(region: dict, old_window: dict, new_window: dict) -> dict:
    """Carry a region over when its window moves and resizes: same relative position inside the window."""
    sx = new_window["w"] / old_window["w"]
    sy = new_window["h"] / old_window["h"]
    return {"x": int(new_window["x"] + (region["x"] - old_window["x"]) * sx),
            "y": int(new_window["y"] + (region["y"] - old_window["y"]) * sy),
            "w": int(region["w"] * sx), "h": int(region["h"] * sy)}


def window_at(x: float, y: float) -> tuple[int, dict] | None:
    """(pid, bounds) of the topmost normal window of another app under a Quartz point."""
    options = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
    for info in CGWindowListCopyWindowInfo(options, kCGNullWindowID) or []:
        if info.get("kCGWindowLayer") != 0 or info.get("kCGWindowOwnerPID") == os.getpid():
            continue
        b = info.get("kCGWindowBounds") or {}
        bounds = {"x": int(b.get("X", 0)), "y": int(b.get("Y", 0)),
                  "w": int(b.get("Width", 0)), "h": int(b.get("Height", 0))}
        if bounds["x"] <= x < bounds["x"] + bounds["w"] and bounds["y"] <= y < bounds["y"] + bounds["h"]:
            return int(info["kCGWindowOwnerPID"]), bounds
    return None


def _ax_frame(window) -> dict | None:
    err, pos = AXUIElementCopyAttributeValue(window, "AXPosition", None)
    err2, size = AXUIElementCopyAttributeValue(window, "AXSize", None)
    if err or err2:
        return None
    ok, point = AXValueGetValue(pos, kAXValueCGPointType, None)
    ok2, dims = AXValueGetValue(size, kAXValueCGSizeType, None)
    if not (ok and ok2):
        return None
    return {"x": int(point.x), "y": int(point.y), "w": int(dims.width), "h": int(dims.height)}


def move_window(pid: int, bounds: dict, target: dict) -> dict | None:
    """Move and resize another app's window via Accessibility. Returns its new frame, or None."""
    if not AXIsProcessTrusted():
        L.warning("Keine Bedienungshilfen-Berechtigung, Fenster wird nicht verschoben")
        return None
    err, windows = AXUIElementCopyAttributeValue(AXUIElementCreateApplication(pid), "AXWindows", None)
    if err or not windows:
        L.warning(f"Fensterliste von PID {pid} nicht lesbar (AX-Fehler {err})")
        return None

    def distance(window) -> float:
        frame = _ax_frame(window)
        if frame is None:
            return float("inf")
        return sum(abs(frame[k] - bounds[k]) for k in ("x", "y", "w", "h"))

    window = min(windows, key=distance)
    if distance(window) > 40:
        L.warning("Kein passendes Fenster gefunden")
        return None
    AXUIElementSetAttributeValue(window, "AXPosition",
                                 AXValueCreate(kAXValueCGPointType, CGPoint(target["x"], target["y"])))
    AXUIElementSetAttributeValue(window, "AXSize",
                                 AXValueCreate(kAXValueCGSizeType, CGSize(target["w"], target["h"])))
    return _ax_frame(window)


def arrange(region: dict) -> dict:
    """Compute the split and move the table window. Returns {"panel": frame, "region": dict | None}.

    "region" is the capture region carried over into the moved window, or None if the window
    could not be moved (then only the panel docks and the region stays as it is).
    """
    panel, table = split_frames(region)
    found = window_at(region["x"] + region["w"] / 2, region["y"] + region["h"] / 2)
    if not found:
        L.warning("Kein Fenster unter der Region gefunden")
        return {"panel": panel, "region": None}
    pid, bounds = found
    moved = move_window(pid, bounds, table)
    if not moved:
        return {"panel": panel, "region": None}
    L.info(f"Tischfenster (PID {pid}) verschoben: {bounds} → {moved}")
    return {"panel": panel, "region": map_region(region, bounds, moved)}

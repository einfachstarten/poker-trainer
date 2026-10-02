"""Always-on-top rectangle showing the active capture region.

Two modes:
- View mode (default): click-through outline so you can keep playing.
- Edit mode: solid frame, drag-to-move, bottom-right corner to resize. Toggled
  from the menubar; saves to config via callback when you let go.
"""

from __future__ import annotations

import log
from AppKit import (
    NSWindow, NSView, NSColor, NSBezierPath,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
    NSStatusWindowLevel, NSMakeRect, NSScreen,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
)
import objc

L = log.get("indicator")

VIEW_COLOR = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 1.0, 0.4, 0.55)
EDIT_COLOR = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.7, 0.1, 0.95)
GRIP_SIZE = 18
MIN_W, MIN_H = 120, 120


class _IndicatorView(NSView):
    """Draws outline; in edit mode handles drag/resize on the window."""

    def initWithFrame_(self, frame):
        self = objc.super(_IndicatorView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._editing = False
        self._on_change = None
        self._drag_origin = None
        self._resizing = False
        self._resize_origin = None
        self._resize_frame = None
        return self

    def setEditing_(self, editing):
        self._editing = bool(editing)
        self.setNeedsDisplay_(True)

    def acceptsFirstMouse_(self, event):
        return True

    def drawRect_(self, rect):
        bounds = self.bounds()
        if self._editing:
            color = EDIT_COLOR
            line_width = 2.5
        else:
            color = VIEW_COLOR
            line_width = 1.5
        color.set()
        path = NSBezierPath.bezierPathWithRect_(
            NSMakeRect(line_width / 2, line_width / 2,
                       bounds.size.width - line_width,
                       bounds.size.height - line_width)
        )
        path.setLineWidth_(line_width)
        path.stroke()
        if self._editing:
            # Resize grip dots in bottom-right
            color.set()
            for i in range(3):
                for j in range(3 - i):
                    NSBezierPath.fillRect_(NSMakeRect(
                        bounds.size.width - 6 - i * 5,
                        5 + j * 5, 2.5, 2.5))

    def _in_grip(self, point):
        b = self.bounds()
        return (point.x > b.size.width - GRIP_SIZE and point.y < GRIP_SIZE)

    def mouseDown_(self, event):
        if not self._editing:
            return
        loc = event.locationInWindow()
        if self._in_grip(loc):
            self._resizing = True
            self._resize_origin = self.window().convertPointToScreen_(loc)
            self._resize_frame = self.window().frame()
        else:
            self._resizing = False
            self._drag_origin = loc

    def mouseDragged_(self, event):
        if not self._editing:
            return
        if self._resizing:
            screen_loc = self.window().convertPointToScreen_(
                event.locationInWindow())
            dx = screen_loc.x - self._resize_origin.x
            dy = screen_loc.y - self._resize_origin.y
            orig = self._resize_frame
            new_w = max(MIN_W, orig.size.width + dx)
            new_h = max(MIN_H, orig.size.height - dy)
            new_y = orig.origin.y + (orig.size.height - new_h)
            self.window().setFrame_display_(
                NSMakeRect(orig.origin.x, new_y, new_w, new_h), True)
            self.setNeedsDisplay_(True)
        else:
            screen_loc = event.locationInWindow()
            origin = self.window().frame().origin
            new_x = origin.x + (screen_loc.x - self._drag_origin.x)
            new_y = origin.y + (screen_loc.y - self._drag_origin.y)
            self.window().setFrameOrigin_((new_x, new_y))

    def mouseUp_(self, event):
        if not self._editing or not self._on_change:
            return
        f = self.window().frame()
        self._on_change(int(f.origin.x), int(f.origin.y),
                        int(f.size.width), int(f.size.height))


class RegionIndicator:
    """Wraps an NSWindow showing a Quartz-coords region."""

    def __init__(self, on_region_change=None):
        """on_region_change(region_dict) is called after every drag/resize end."""
        self._window = None
        self._view = None
        self._on_region_change = on_region_change

    def show(self, region: dict):
        self.hide()
        x = int(region["x"])
        y = int(region["y"])
        w = int(region["w"])
        h = int(region["h"])

        screen_h = int(NSScreen.mainScreen().frame().size.height)
        cocoa_y = screen_h - y - h

        frame = NSMakeRect(x, cocoa_y, w, h)
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False,
        )
        self._window.setLevel_(NSStatusWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setHasShadow_(False)
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
        )

        self._view = _IndicatorView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        self._view._on_change = self._on_change_cocoa
        self._window.setContentView_(self._view)
        self._window.orderFrontRegardless()
        L.info(f"Region indicator gezeigt bei ({x},{y}) {w}x{h}")

    def hide(self):
        if self._window:
            self._window.orderOut_(None)
            self._window.close()
            self._window = None
            self._view = None

    def set_editing(self, editing: bool):
        if not self._window:
            return
        self._window.setIgnoresMouseEvents_(not editing)
        if self._view:
            self._view.setEditing_(editing)
        L.info(f"Region indicator edit-mode: {editing}")

    def _on_change_cocoa(self, cocoa_x, cocoa_y, w, h):
        # Cocoa origin = bottom-left → Quartz origin = top-left.
        screen_h = int(NSScreen.mainScreen().frame().size.height)
        quartz_y = screen_h - cocoa_y - h
        region = {"x": int(cocoa_x), "y": int(quartz_y),
                  "w": int(w), "h": int(h)}
        L.info(f"Region geändert via Indicator: {region}")
        if self._on_region_change:
            self._on_region_change(region)

"""Always-on-top overlay window using PyObjC (compatible with rumps event loop)."""

from __future__ import annotations

import log
from AppKit import (
    NSWindow, NSView, NSTextField, NSFont, NSColor,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskResizable,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSMakeRect,
    NSLineBreakByWordWrapping,
    NSViewWidthSizable, NSViewHeightSizable,
    NSViewMaxYMargin, NSViewMinYMargin, NSViewMaxXMargin,
)
import objc

L = log.get("overlay")

WIN_W = 440
WIN_H = 280
MIN_W = 280
MIN_H = 120
GRIP_SIZE = 16

BG_COLOR = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.1, 0.18, 0.92)


class OverlayView(NSView):
    """Custom view: drag to move, bottom-right corner to resize."""

    def initWithFrame_(self, frame):
        self = objc.super(OverlayView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._drag_origin = None
        self._resizing = False
        self._resize_origin = None
        self._resize_frame = None
        return self

    def _in_grip(self, point):
        """Check if point is in bottom-right resize grip area."""
        bounds = self.bounds()
        return (point.x > bounds.size.width - GRIP_SIZE and
                point.y < GRIP_SIZE)

    def mouseDown_(self, event):
        loc = event.locationInWindow()
        if self._in_grip(loc):
            self._resizing = True
            self._resize_origin = self.window().convertPointToScreen_(loc)
            self._resize_frame = self.window().frame()
        else:
            self._resizing = False
            self._drag_origin = loc

    def mouseDragged_(self, event):
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
        else:
            screen_loc = event.locationInWindow()
            origin = self.window().frame().origin
            new_x = origin.x + (screen_loc.x - self._drag_origin.x)
            new_y = origin.y + (screen_loc.y - self._drag_origin.y)
            self.window().setFrameOrigin_((new_x, new_y))

    def drawRect_(self, rect):
        """Draw background + resize grip indicator."""
        BG_COLOR.set()
        from AppKit import NSBezierPath
        NSBezierPath.fillRect_(rect)

        # Draw grip dots in bottom-right
        bounds = self.bounds()
        grip_color = NSColor.colorWithCalibratedWhite_alpha_(0.4, 1.0)
        grip_color.set()
        for i in range(3):
            for j in range(3 - i):
                x = bounds.size.width - 6 - i * 5
                y = 5 + j * 5
                NSBezierPath.fillRect_(NSMakeRect(x, y, 2, 2))


class Overlay:
    def __init__(self, position: dict | None = None, size: dict | None = None):
        self._window = None
        self._action_label = None
        self._reason_label = None
        self._hand_label = None
        self._position = position or {"x": 50, "y": 50}
        self._size = size or {"w": WIN_W, "h": WIN_H}
        L.debug(f"Init position={self._position} size={self._size}")

    def start(self):
        x = self._position["x"]
        y = self._position["y"]
        w = self._size.get("w", WIN_W)
        h = self._size.get("h", WIN_H)

        frame = NSMakeRect(x, y, w, h)
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskResizable
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False,
        )
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setAlphaValue_(0.92)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setMovableByWindowBackground_(False)
        self._window.setHasShadow_(True)
        self._window.setMinSize_((MIN_W, MIN_H))

        content = OverlayView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        content.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self._window.setContentView_(content)

        # Action label (top, stretches with width)
        self._action_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, h - 45, w - 24, 38))
        self._action_label.setStringValue_("Drücke F1 zum Analysieren")
        self._action_label.setFont_(NSFont.fontWithName_size_("Menlo-Bold", 24))
        self._action_label.setTextColor_(NSColor.grayColor())
        self._action_label.setBezeled_(False)
        self._action_label.setDrawsBackground_(False)
        self._action_label.setEditable_(False)
        self._action_label.setSelectable_(False)
        self._action_label.setAutoresizingMask_(
            NSViewWidthSizable | NSViewMinYMargin)
        content.addSubview_(self._action_label)

        # Reason label (middle, stretches both ways)
        self._reason_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, 38, w - 24, h - 90))
        self._reason_label.setStringValue_("")
        self._reason_label.setFont_(NSFont.fontWithName_size_("Menlo", 13))
        self._reason_label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.75, 1.0))
        self._reason_label.setBezeled_(False)
        self._reason_label.setDrawsBackground_(False)
        self._reason_label.setEditable_(False)
        self._reason_label.setSelectable_(False)
        self._reason_label.setLineBreakMode_(NSLineBreakByWordWrapping)
        self._reason_label.setMaximumNumberOfLines_(0)
        self._reason_label.setAutoresizingMask_(
            NSViewWidthSizable | NSViewHeightSizable)
        content.addSubview_(self._reason_label)

        # Hand/Board label (bottom, stretches with width, wraps)
        self._hand_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, 10, w - 24, 40))
        self._hand_label.setStringValue_("")
        self._hand_label.setFont_(NSFont.fontWithName_size_("Menlo", 12))
        self._hand_label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.5, 1.0))
        self._hand_label.setBezeled_(False)
        self._hand_label.setDrawsBackground_(False)
        self._hand_label.setEditable_(False)
        self._hand_label.setSelectable_(False)
        self._hand_label.setLineBreakMode_(NSLineBreakByWordWrapping)
        self._hand_label.setMaximumNumberOfLines_(0)
        self._hand_label.setAutoresizingMask_(
            NSViewWidthSizable | NSViewMaxYMargin)
        content.addSubview_(self._hand_label)

        self._window.orderFrontRegardless()
        L.info(f"Overlay sichtbar bei ({x}, {y}), {w}x{h}")

    def _hex_to_nscolor(self, hex_color: str) -> NSColor:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)

    def update_tip(self, action: str, amount: str, reason: str,
                   hand: str = "", board: str = "", color: str = "#00CC00",
                   pot_odds: str = "-", equity: str = "-"):
        if self._action_label is None:
            return

        display = f"→ {action}"
        if amount and amount != "-":
            display += f" ${amount}"

        hand_info = ""
        if hand and hand != "?":
            hand_info = f"Hand: {hand}"
            if board and board != "-":
                hand_info += f"  |  Board: {board}"
        extras = []
        if pot_odds and pot_odds != "-":
            extras.append(f"Odds: {pot_odds}")
        if equity and equity != "-":
            extras.append(f"Equity: {equity}")
        if extras:
            hand_info += f"  |  {' | '.join(extras)}" if hand_info else " | ".join(extras)

        L.debug(f"Update overlay: {display}")

        def _do_update():
            self._action_label.setStringValue_(display)
            self._action_label.setTextColor_(self._hex_to_nscolor(color))
            self._reason_label.setStringValue_(reason)
            self._hand_label.setStringValue_(hand_info)

        from PyObjCTools import AppHelper
        AppHelper.callAfter(_do_update)

    def update_status(self, text: str):
        if self._action_label is None:
            return
        L.debug(f"Status: {text}")

        def _do_update():
            self._action_label.setStringValue_(text)
            self._action_label.setTextColor_(NSColor.grayColor())
            self._reason_label.setStringValue_("")
            self._hand_label.setStringValue_("")

        from PyObjCTools import AppHelper
        AppHelper.callAfter(_do_update)

    def get_position(self) -> dict:
        if self._window:
            frame = self._window.frame()
            return {"x": int(frame.origin.x), "y": int(frame.origin.y)}
        return dict(self._position)

    def get_size(self) -> dict:
        if self._window:
            frame = self._window.frame()
            return {"w": int(frame.size.width), "h": int(frame.size.height)}
        return dict(self._size)

    def stop(self):
        L.info("Overlay wird geschlossen")
        if self._window:
            def _close():
                self._window.orderOut_(None)
            from PyObjCTools import AppHelper
            AppHelper.callAfter(_close)
            self._window = None

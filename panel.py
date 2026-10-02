"""Companion panel: a normal window next to the table, rendered as a local web page."""

from __future__ import annotations

import json
import os

import log
import objc
from AppKit import (
    NSWindow, NSScreen, NSColor, NSAppearance,
    NSWindowStyleMaskTitled, NSWindowStyleMaskResizable,
    NSBackingStoreBuffered, NSFloatingWindowLevel, NSMakeRect,
)
from Foundation import NSObject, NSURL
from PyObjCTools import AppHelper
from WebKit import WKWebView, WKWebViewConfiguration, WKUserContentController

L = log.get("panel")

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
DEFAULT_W = 440
MIN_W, MIN_H = 360, 520


class _Bridge(NSObject, protocols=[objc.protocolNamed("WKScriptMessageHandler")]):
    """Receives messages posted by the page's JavaScript."""

    _callback = None

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        if self._callback:
            self._callback(dict(message.body()))


class Panel:
    def __init__(self, frame: dict | None = None, on_message=None):
        """frame: window frame {"x", "y", "w", "h"} in Cocoa screen coordinates. on_message(dict) gets page events."""
        self._frame = frame
        self._on_message = on_message
        self._window = None
        self._web = None
        self._bridge = None
        self._ready = False
        self._model: dict | None = None

    def start(self):
        """Create and show the window. Must run on the main thread."""
        frame = self._frame or self._default_frame()
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskResizable
        rect = NSWindow.contentRectForFrameRect_styleMask_(
            NSMakeRect(frame["x"], frame["y"], frame["w"], frame["h"]), style)
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False,
        )
        self._window.setTitle_("Poker Companion")
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setMinSize_((MIN_W, MIN_H))
        self._window.setReleasedWhenClosed_(False)
        self._window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.055, 0.09, 0.078, 1))
        self._window.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))

        config = WKWebViewConfiguration.alloc().init()
        controller = WKUserContentController.alloc().init()
        self._bridge = _Bridge.alloc().init()
        self._bridge._callback = self._on_page_message
        controller.addScriptMessageHandler_name_(self._bridge, "bridge")
        config.setUserContentController_(controller)

        self._web = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, rect.size.width, rect.size.height), config)
        self._window.setContentView_(self._web)
        page = NSURL.fileURLWithPath_(os.path.join(UI_DIR, "panel.html"))
        self._web.loadFileURL_allowingReadAccessToURL_(page, NSURL.fileURLWithPath_(UI_DIR))
        self._window.orderFrontRegardless()
        L.info(f"Panel sichtbar bei ({frame['x']}, {frame['y']}), {frame['w']}x{frame['h']}")

    @staticmethod
    def _default_frame() -> dict:
        visible = NSScreen.mainScreen().visibleFrame()
        return {"x": int(visible.origin.x + visible.size.width - DEFAULT_W), "y": int(visible.origin.y),
                "w": DEFAULT_W, "h": int(visible.size.height)}

    def _on_page_message(self, message: dict):
        if message.get("type") == "ready":
            self._ready = True
            if self._model is not None:
                self._push(self._model)
            return
        if self._on_message:
            self._on_message(message)

    def render(self, model: dict):
        """Show a view model. Safe to call from any thread."""
        self._model = model
        if self._ready:
            AppHelper.callAfter(self._push, model)

    def _push(self, model: dict):
        if self._web is not None:
            self._web.evaluateJavaScript_completionHandler_(f"update({json.dumps(model)})", None)

    def set_frame(self, frame: dict):
        if self._window:
            self._window.setFrame_display_(
                NSMakeRect(frame["x"], frame["y"], frame["w"], frame["h"]), True)

    def get_frame(self) -> dict | None:
        if not self._window:
            return self._frame
        f = self._window.frame()
        return {"x": int(f.origin.x), "y": int(f.origin.y),
                "w": int(f.size.width), "h": int(f.size.height)}

    def stop(self):
        if self._window:
            window, self._window = self._window, None
            self._web = None
            self._ready = False
            window.orderOut_(None)
            window.close()
            L.info("Panel geschlossen")

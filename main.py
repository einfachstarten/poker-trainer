"""Poker Trainer MVP — main entry point with menubar + hotkey trigger."""

from __future__ import annotations

import sys
import threading
import time

import rumps
from Quartz import (
    CGEventMaskBit, kCGEventKeyDown,
    CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
    CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
    kCGEventTapOptionListenOnly,
    CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent,
    CFRunLoopAddSource, kCFRunLoopCommonModes, CFRunLoopRun,
)

import log
log.setup()
L = log.get("main")

import config
import capture
import analyzer
import overlay
import selector
import history

# F1 = 122, F2 = 120, F3 = 99
HOTKEY_CODE = 122
HOTKEY_NAME = "F1"
NEWROUND_CODE = 120
NEWROUND_NAME = "F2"
DETAIL_CODE = 99
DETAIL_NAME = "F3"


class PokerTrainerApp(rumps.App):
    def __init__(self):
        super().__init__("Poker Trainer", icon=None, title="♠️")
        self.cfg = config.load()
        L.info(f"Config geladen: region={self.cfg.get('crop_region')}")
        self.running = False
        self.overlay_win: overlay.Overlay | None = None
        self.analyzer_inst: analyzer.Analyzer | None = None
        self._analyzing = False
        self._detailing = False

        self.menu = [
            rumps.MenuItem("Start", callback=self.toggle),
            rumps.MenuItem("Neue Region", callback=self.new_region),
            rumps.MenuItem("Stats", callback=self.show_stats),
            None,
        ]

    def toggle(self, sender):
        if self.running:
            L.info("Toggle → Stop")
            self.stop_monitoring()
            sender.title = "Start"
        else:
            L.info("Toggle → Start")
            self.start_monitoring()
            sender.title = "Stop"

    def new_region(self, _):
        L.info("Neue Region angefordert")
        was_running = self.running
        if was_running:
            self.stop_monitoring()

        region = selector.select_region()
        if region:
            self.cfg["crop_region"] = region
            config.save(self.cfg)
            L.info(f"Region gespeichert: {region}")
            if was_running:
                self.start_monitoring()
                for item in self.menu.values():
                    if hasattr(item, 'title') and item.title in ("Start", "Stop"):
                        item.title = "Stop"
                        break
        else:
            L.info("Region-Auswahl abgebrochen")

    def show_stats(self, _):
        stats = history.get_session_stats()
        L.info(f"Stats: {stats}")
        rumps.alert("Poker Trainer Stats", stats)

    def start_monitoring(self):
        api_key = config.get_api_key(self.cfg)
        if not api_key:
            L.error("Kein API Key!")
            rumps.alert(
                "API Key fehlt",
                "Setze ANTHROPIC_API_KEY oder trage ihn in ~/.poker-trainer/config.json ein"
            )
            return

        if not config.has_region(self.cfg):
            L.info("Keine Region → öffne Selector")
            region = selector.select_region()
            if not region:
                L.info("Selector abgebrochen")
                return
            self.cfg["crop_region"] = region
            config.save(self.cfg)
            L.info(f"Region gespeichert: {region}")

        L.info(f"Starte Monitoring mit Region {self.cfg['crop_region']}")

        self.analyzer_inst = analyzer.Analyzer(
            api_key=api_key,
            model=self.cfg.get("model", "claude-sonnet-4-6"),
        )

        self.overlay_win = overlay.Overlay(
            position=self.cfg.get("overlay_position"),
            size=self.cfg.get("overlay_size"),
        )
        self.overlay_win.start()
        L.info("Overlay gestartet")

        self.running = True
        self._analyzing = False
        self._detailing = False

        self._hotkey_thread = threading.Thread(target=self._listen_hotkey, daemon=True)
        self._hotkey_thread.start()
        L.info(f"Hotkeys: {HOTKEY_NAME}=Analyse, {NEWROUND_NAME}=Neue Runde, {DETAIL_NAME}=Detail")

    def stop_monitoring(self):
        L.info("Stoppe Monitoring")
        self.running = False

        if self.overlay_win:
            self.cfg["overlay_position"] = self.overlay_win.get_position()
            self.cfg["overlay_size"] = self.overlay_win.get_size()
            config.save(self.cfg)
            self.overlay_win.stop()
            self.overlay_win = None
            L.info("Overlay gestoppt, Position gespeichert")

    def _listen_hotkey(self):
        """Listen for global hotkey events via Quartz Event Tap."""

        def callback(proxy, event_type, event, refcon):
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            if keycode == HOTKEY_CODE and self.running and not self._analyzing:
                L.info(f"{HOTKEY_NAME} gedrückt!")
                threading.Thread(target=self._do_analysis, daemon=True).start()
            elif keycode == NEWROUND_CODE and self.running:
                L.info(f"{NEWROUND_NAME} gedrückt — Neue Runde!")
                self._new_round()
            elif keycode == DETAIL_CODE and self.running and not self._detailing:
                L.info(f"{DETAIL_NAME} gedrückt — Detail laden!")
                threading.Thread(target=self._do_detail, daemon=True).start()
            return event

        mask = CGEventMaskBit(kCGEventKeyDown)
        tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly, mask, callback, None,
        )
        if tap is None:
            L.error("Event Tap konnte nicht erstellt werden! Accessibility-Berechtigung nötig.")
            return

        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
        L.debug("Event Tap aktiv, warte auf Hotkey...")
        CFRunLoopRun()

    def _new_round(self):
        """Reset opponent history and overlay for a new round."""
        if self.analyzer_inst:
            count = len(self.analyzer_inst._opponent_history)
            self.analyzer_inst._opponent_history.clear()
            L.info(f"Opponent history geleert ({count} Einträge)")
        if self.overlay_win:
            self.overlay_win.update_status(f"Neue Runde — {HOTKEY_NAME} zum Analysieren")

    def _do_analysis(self):
        """Run quick analysis: ACTION, AMOUNT, HAND, POTODDS, EQUITY."""
        if self._analyzing or not self.running:
            return
        self._analyzing = True

        try:
            region = self.cfg["crop_region"]

            if self.overlay_win:
                self.overlay_win.update_status("Analysiere...")

            img = capture.capture_region_pil(region)
            if img is None:
                L.warning("Capture fehlgeschlagen")
                if self.overlay_win:
                    self.overlay_win.update_status("Capture fehlgeschlagen")
                return

            t0 = time.time()
            L.info(f"Quick-Analyse ({self.analyzer_inst.model})...")

            def on_action(action):
                dt = time.time() - t0
                L.info(f"ACTION nach {dt:.1f}s: {action}")
                if self.overlay_win:
                    color = "#00CC00"
                    if action in ("FOLD",):
                        color = "#FF4444"
                    elif action in ("CALL", "CHECK"):
                        color = "#FFAA00"
                    elif action == "WAIT":
                        color = "#666666"
                    self.overlay_win.update_tip(action, "", "", color=color)

            tip = self.analyzer_inst.analyze_quick(img, on_action=on_action)
            dt = time.time() - t0

            if tip and self.overlay_win:
                if tip.is_actionable:
                    self.overlay_win.update_tip(
                        tip.action, tip.amount,
                        f"F3 für Details",
                        tip.hand, "", tip.color,
                        tip.pot_odds, tip.equity,
                    )
                    L.info(f"Quick nach {dt:.1f}s: {tip.action} {tip.amount} Odds={tip.pot_odds} Eq={tip.equity}")
                else:
                    self.overlay_win.update_status(
                        f"Warte... ({HOTKEY_NAME} zum Analysieren)"
                    )
                    L.info(f"WAIT nach {dt:.1f}s")

                history.log_hand(tip, dt)

            elif not tip:
                L.warning(f"Quick-Analyse fehlgeschlagen nach {dt:.1f}s")
                if self.overlay_win:
                    self.overlay_win.update_status("Fehler — nochmal F1")

        finally:
            self._analyzing = False

    def _do_detail(self):
        """Load detailed analysis: REASON, BOARD, OPPONENTS."""
        if self._detailing or not self.running:
            return
        if not self.analyzer_inst or not self.analyzer_inst._last_quick_tip:
            L.warning("Kein Quick-Result vorhanden — erst F1 drücken")
            return

        self._detailing = True
        try:
            if self.overlay_win:
                quick = self.analyzer_inst._last_quick_tip
                self.overlay_win.update_tip(
                    quick.action, quick.amount,
                    "Lade Details...",
                    quick.hand, "", quick.color,
                    quick.pot_odds, quick.equity,
                )

            t0 = time.time()
            tip = self.analyzer_inst.analyze_detail()
            dt = time.time() - t0

            if tip and self.overlay_win:
                self.overlay_win.update_tip(
                    tip.action, tip.amount, tip.reason,
                    tip.hand, tip.board, tip.color,
                    tip.pot_odds, tip.equity,
                )
                L.info(f"Detail nach {dt:.1f}s: {tip.reason[:60]}...")
            elif not tip:
                L.warning(f"Detail fehlgeschlagen nach {dt:.1f}s")
        finally:
            self._detailing = False

    @rumps.clicked("Quit")
    def on_quit(self, _):
        L.info("Quit angefordert")
        self.stop_monitoring()
        rumps.quit_application()


def main():
    cfg = config.load()
    api_key = config.get_api_key(cfg)

    if not api_key:
        L.error("ANTHROPIC_API_KEY nicht gesetzt!")
        sys.exit(1)

    L.info("App startet...")
    app = PokerTrainerApp()
    app.run()


if __name__ == "__main__":
    main()

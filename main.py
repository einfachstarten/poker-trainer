"""Poker Trainer MVP — main entry point with menubar + hotkey trigger."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request

VERSION = "1.2.0"
REPO = "einfachstarten/poker-trainer"
PID_FILE = os.path.expanduser("~/.poker-trainer/poker-trainer.pid")
APP_DIR = os.path.dirname(os.path.abspath(__file__))

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

        self._current_style = self.cfg.get("play_style", analyzer.DEFAULT_STYLE)
        current_name = analyzer.PLAY_STYLES.get(self._current_style, {}).get("name", "TAG")
        self._style_button = rumps.MenuItem(f"Stil: {current_name}", callback=self._cycle_style)

        self._update_button = rumps.MenuItem(f"Version {VERSION}", callback=None)
        self._update_button.set_callback(None)

        self.menu = [
            rumps.MenuItem("Start", callback=self.toggle),
            rumps.MenuItem("Neue Region", callback=self.new_region),
            self._style_button,
            rumps.MenuItem("Stats", callback=self.show_stats),
            None,
            self._update_button,
        ]

        threading.Thread(target=self._check_for_update, daemon=True).start()

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

    def _cycle_style(self, sender):
        keys = list(analyzer.PLAY_STYLES.keys())
        idx = keys.index(self._current_style) if self._current_style in keys else 0
        new_key = keys[(idx + 1) % len(keys)]

        self._current_style = new_key
        self.cfg["play_style"] = new_key
        config.save(self.cfg)
        if self.analyzer_inst:
            self.analyzer_inst.set_style(new_key)

        sender.title = f"Stil: {analyzer.PLAY_STYLES[new_key]['name']}"
        L.info(f"Spielstil: {analyzer.PLAY_STYLES[new_key]['name']}")

    def show_stats(self, _):
        stats = history.get_session_stats()
        L.info(f"Stats: {stats}")
        rumps.alert("Poker Trainer Stats", stats)

    def start_monitoring(self):
        if self.overlay_win:
            L.warning("Overlay existiert bereits, überspringe")
            return

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
            style=self.cfg.get("play_style", analyzer.DEFAULT_STYLE),
        )

        self.overlay_win = overlay.Overlay(
            position=self.cfg.get("overlay_position"),
            size=self.cfg.get("overlay_size"),
            on_button=self._on_overlay_button,
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

    def _check_for_update(self):
        """Check GitHub releases API for newer version."""
        try:
            url = f"https://api.github.com/repos/{REPO}/releases"
            req = urllib.request.Request(url, headers={"User-Agent": "PokerTrainer"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                releases = json.loads(resp.read())

            if not releases:
                return

            # Find highest version tag
            latest_tag = None
            for r in releases:
                tag = r.get("tag_name", "").lstrip("v")
                if not latest_tag or self._version_tuple(tag) > self._version_tuple(latest_tag):
                    latest_tag = tag

            if latest_tag and self._version_tuple(latest_tag) > self._version_tuple(VERSION):
                L.info(f"Update verfügbar: v{latest_tag} (aktuell: v{VERSION})")
                self._update_button.title = f"⬆ Update → v{latest_tag}"
                self._update_button.set_callback(self._do_update)
            else:
                L.info(f"Kein Update (v{VERSION} ist aktuell)")
        except Exception as e:
            L.warning(f"Update-Check fehlgeschlagen: {e}")

    @staticmethod
    def _version_tuple(v: str) -> tuple:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    def _do_update(self, _):
        """Pull latest code and restart."""
        L.info("Update wird durchgeführt...")
        self._update_button.title = "Updating..."
        self._update_button.set_callback(None)

        def _run_update():
            try:
                result = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=APP_DIR, capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    L.error(f"git pull fehlgeschlagen: {result.stderr}")
                    rumps.alert("Update fehlgeschlagen", result.stderr)
                    self._update_button.title = "Update fehlgeschlagen"
                    return

                L.info(f"git pull OK: {result.stdout.strip()}")
                rumps.alert("Update installiert", f"Poker Trainer wird neu gestartet.")
                # Restart
                self.stop_monitoring()
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception as e:
                L.error(f"Update Error: {e}")
                rumps.alert("Update fehlgeschlagen", str(e))

        threading.Thread(target=_run_update, daemon=True).start()

    def _speak(self, text):
        """Speak text using macOS say in background."""
        clean = text.replace("♠", " spades").replace("♦", " diamonds")
        clean = clean.replace("♥", " hearts").replace("♣", " clubs")
        clean = clean.replace("→", "").replace("—", ",")
        subprocess.Popen(["say", "-v", "Daniel", clean])

    def _on_overlay_button(self, tag):
        """Handle overlay button clicks: 1=quick, 2=newround, 3=detail."""
        if not self.running:
            return
        if tag == 1 and not self._analyzing:
            L.info("Button: Quick-Analyse")
            threading.Thread(target=self._do_analysis, daemon=True).start()
        elif tag == 2:
            L.info("Button: Neue Runde")
            self._new_round()
        elif tag == 3 and not self._detailing:
            L.info("Button: Detail")
            threading.Thread(target=self._do_detail, daemon=True).start()

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
                if tip.reason:
                    self._speak(tip.reason)
            elif not tip:
                L.warning(f"Detail fehlgeschlagen nach {dt:.1f}s")
        finally:
            self._detailing = False

    def terminate(self):
        L.info("Quit angefordert")
        self.stop_monitoring()
        super().terminate()


def _kill_existing():
    """Kill any existing instance via PID file."""
    if not os.path.exists(PID_FILE):
        return
    try:
        old_pid = int(open(PID_FILE).read().strip())
        os.kill(old_pid, signal.SIGTERM)
        L.info(f"Alte Instanz (PID {old_pid}) beendet")
        time.sleep(0.5)
    except (ProcessLookupError, ValueError):
        pass  # already dead
    except PermissionError:
        L.warning(f"Konnte PID {old_pid} nicht beenden")


def _write_pid():
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    open(PID_FILE, "w").write(str(os.getpid()))


def _cleanup_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def main():
    cfg = config.load()
    api_key = config.get_api_key(cfg)

    if not api_key:
        L.error("ANTHROPIC_API_KEY nicht gesetzt!")
        sys.exit(1)

    _kill_existing()
    _write_pid()

    import atexit
    atexit.register(_cleanup_pid)

    L.info("App startet...")
    app = PokerTrainerApp()
    app.run()


if __name__ == "__main__":
    main()

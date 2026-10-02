"""Poker Companion — main entry point: menubar, hotkeys, wiring of the companion."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request

import bootstrap
bootstrap.ensure_requirements()

VERSION = "1.4.1"
REPO = "einfachstarten/poker-trainer"
PID_FILE = os.path.expanduser("~/.poker-trainer/poker-trainer.pid")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Inside the app bundle (see launcher.py) an update is downloaded to UPDATE_DIR
# instead of pulled with git, and the app restarts through its own executable.
BUNDLE_EXE = os.environ.get("EXECUTABLEPATH") if getattr(sys, "frozen", False) else None
UPDATE_DIR = os.path.expanduser("~/.poker-trainer/app")

import rumps
from AppKit import NSApplication, NSPasteboard, NSPasteboardTypeString
from PyObjCTools import AppHelper
from Quartz import (
    CGEventMaskBit, kCGEventKeyDown, kCGEventFlagsChanged,
    CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
    CGEventGetFlags, kCGEventFlagMaskAlternate,
    CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
    kCGEventTapOptionListenOnly,
    CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent,
    CFRunLoopAddSource, kCFRunLoopCommonModes, CFRunLoopRun,
    CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess,
    CGPreflightListenEventAccess, CGRequestListenEventAccess,
)

import log
log.setup()
L = log.get("main")

import config
import brain
import companion
import layout
import overlay
import panel
import selector
import history
import region_indicator
import voice_in
import voice_out
from strategy import StrategyProfile

# F1 = 122, F2 = 120, F3 = 99
HOTKEY_CODE = 122
HOTKEY_NAME = "F1"
NEWROUND_CODE = 120
NEWROUND_NAME = "F2"
THINK_CODE = 99
THINK_NAME = "F3"
TALK_CODE = 61  # right Option key: hold to talk


class PokerTrainerApp(rumps.App):
    def __init__(self):
        super().__init__("Poker Trainer", icon=None, title="♠️")
        self.cfg = config.load()
        L.info(f"Config geladen: region={self.cfg.get('crop_region')}")
        self.running = False
        self.view = None  # panel.Panel or overlay.Overlay, whichever layout is active
        self.companion: companion.Companion | None = None
        self.listener: voice_in.Listener | None = None
        self._hotkey_thread = None
        self.region_indicator = region_indicator.RegionIndicator(
            on_region_change=self._on_indicator_region_change,
        )
        self._region_editing = False
        self._capture_hint_shown = False
        self._latest_tag = None

        profile = StrategyProfile.from_dict(self.cfg.get("strategy"))
        self._strategy_button = rumps.MenuItem(f"Strategie: {profile.name}", callback=self._cycle_strategy)

        self._update_button = rumps.MenuItem(f"Version {VERSION}", callback=None)
        self._update_button.set_callback(None)

        self._edit_region_button = rumps.MenuItem("Region anpassen",
                                                  callback=self.toggle_region_edit)

        self.menu = [
            rumps.MenuItem("Start", callback=self.toggle),
            rumps.MenuItem("Split anordnen", callback=self.arrange_split),
            rumps.MenuItem("Neue Region", callback=self.new_region),
            self._edit_region_button,
            self._strategy_button,
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
            sender.title = "Stop" if self.running else "Start"

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

    def toggle_region_edit(self, sender):
        if not self.running:
            rumps.alert("Region anpassen", "Erst auf 'Start' klicken — der Region-Rahmen wird nur im laufenden Monitoring angezeigt.")
            return
        self._region_editing = not self._region_editing
        self.region_indicator.set_editing(self._region_editing)
        sender.title = "Region fixieren" if self._region_editing else "Region anpassen"

    def _on_indicator_region_change(self, region: dict):
        self.cfg["crop_region"] = region
        config.save(self.cfg)
        L.info(f"Region durch Indicator-Drag aktualisiert: {region}")

    def _cycle_strategy(self, _):
        """Step through the presets. Fine tuning happens with the dials in the panel."""
        if self.companion:
            self.companion.cycle_preset()
            return
        names = list(companion.PRESETS)
        current = StrategyProfile.from_dict(self.cfg.get("strategy")).name
        nxt = names[(names.index(current) + 1) % len(names)] if current in names else names[0]
        self.cfg["strategy"] = StrategyProfile.from_preset(nxt).to_dict()
        self._save_cfg(self.cfg)

    def _save_cfg(self, cfg: dict):
        """Persist settings and keep the menu in step (the companion calls this from its threads)."""
        config.save(cfg)
        name = StrategyProfile.from_dict(cfg.get("strategy")).name
        AppHelper.callAfter(setattr, self._strategy_button, "title", f"Strategie: {name}")

    def arrange_split(self, _):
        """Dock the panel on the right and move the table window to the left of it."""
        if not self.running or not isinstance(self.view, panel.Panel):
            rumps.alert("Split anordnen", "Erst auf 'Start' klicken (Layout: Split).")
            return
        result = layout.arrange(self.cfg["crop_region"])
        self.view.set_frame(result["panel"])
        if result["region"]:
            self.cfg["crop_region"] = result["region"]
            config.save(self.cfg)
            self.region_indicator.show(result["region"])
            L.info(f"Split angeordnet, Region jetzt {result['region']}")
        else:
            rumps.alert("Split anordnen",
                        "Das Tischfenster ließ sich nicht verschieben. Das Panel sitzt rechts, "
                        "bitte das Tischfenster von Hand daneben legen und 'Region anpassen' nutzen.")

    def show_stats(self, _):
        stats = history.get_session_stats()
        L.info(f"Stats: {stats}")
        rumps.alert("Poker Trainer Stats", stats)

    def start_monitoring(self):
        if self.companion:
            L.warning("Companion läuft bereits, überspringe")
            return

        # Without this permission every capture only shows the desktop. Hint
        # once per session; a second click on Start goes ahead regardless.
        if not CGPreflightScreenCaptureAccess() and not self._capture_hint_shown:
            self._capture_hint_shown = True
            L.warning("Keine Berechtigung für Bildschirmaufnahme")
            CGRequestScreenCaptureAccess()
            rumps.alert(
                "Bildschirmaufnahme erlauben",
                "Poker Trainer darf den Bildschirm noch nicht aufnehmen.\n\n"
                "Systemeinstellungen → Datenschutz & Sicherheit → "
                "Bildschirm- & Systemaudioaufnahme: Poker Trainer einschalten. "
                "Danach Poker Trainer beenden und neu starten."
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

        try:
            backend = brain.make_backend(self.cfg, config.get_api_key(self.cfg))
        except brain.BrainError as e:
            L.error(f"Kein Claude-Zugang: {e}")
            rumps.alert(
                "Claude nicht erreichbar",
                f"{e}\n\nEntweder 'claude auth login' im Terminal ausführen oder einen "
                "API Key in ~/.poker-trainer/config.json eintragen."
            )
            return

        if self.cfg.get("layout") == "overlay":
            self.view = overlay.Overlay(
                position=self.cfg.get("overlay_position"),
                size=self.cfg.get("overlay_size"),
                on_button=self._on_overlay_button,
            )
        else:
            self.view = panel.Panel(
                frame=self.cfg.get("panel_frame"),
                on_message=lambda message: self.companion and self.companion.on_view_message(message),
            )
        self.view.start()
        self.region_indicator.show(self.cfg["crop_region"])

        self.companion = companion.Companion(
            self.cfg, backend, self.view,
            voice_out.Speaker(voice_out.make_engine(self.cfg)), save_cfg=self._save_cfg,
        )
        self.companion.start()
        self.running = True
        L.info(f"Companion gestartet ({backend.name})")

        if voice_in.available():
            self.listener = voice_in.Listener(on_text=self.companion.ask,
                                              on_state=self.companion.set_listening)
            threading.Thread(target=voice_in.warm_up, daemon=True).start()
        else:
            L.info("Spracheingabe aus: sounddevice oder mlx-whisper nicht installiert")

        if not CGPreflightListenEventAccess():
            # macOS asks once to allow the hotkeys ("Eingabeüberwachung")
            CGRequestListenEventAccess()

        if self._hotkey_thread is None:  # one event tap for the app's lifetime
            self._hotkey_thread = threading.Thread(target=self._listen_hotkey, daemon=True)
            self._hotkey_thread.start()
        L.info(f"Hotkeys: {HOTKEY_NAME}=Neu lesen, {NEWROUND_NAME}=Neue Hand, {THINK_NAME}=Was denkst du?, "
               "rechte Option-Taste halten=Sprechen")

    def stop_monitoring(self):
        L.info("Stoppe Monitoring")
        self.running = False

        self.region_indicator.hide()

        self.listener = None
        if self.companion:
            self.companion.stop()
            self.companion = None

        if self.view:
            if isinstance(self.view, panel.Panel):
                self.cfg["panel_frame"] = self.view.get_frame()
            else:
                self.cfg["overlay_position"] = self.view.get_position()
                self.cfg["overlay_size"] = self.view.get_size()
            config.save(self.cfg)
            self.view.stop()
            self.view = None
            L.info("Fenster geschlossen, Position gespeichert")

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
                self._latest_tag = latest_tag
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
        """Install the latest code and restart."""
        L.info("Update wird durchgeführt...")
        self._update_button.title = "Updating..."
        self._update_button.set_callback(None)

        def _run_update():
            try:
                if BUNDLE_EXE:
                    _download_release(self._latest_tag)
                    L.info(f"v{self._latest_tag} nach {UPDATE_DIR} geladen")
                else:
                    result = subprocess.run(
                        ["git", "pull", "--ff-only"],
                        cwd=APP_DIR, capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode != 0:
                        raise RuntimeError(result.stderr)
                    L.info(f"git pull OK: {result.stdout.strip()}")
            except Exception as e:
                L.error(f"Update Error: {e}")
                AppHelper.callAfter(self._update_failed, str(e))
                return
            # Alerts and the restart belong on the main thread
            AppHelper.callAfter(self._restart_after_update)

        threading.Thread(target=_run_update, daemon=True).start()

    def _update_failed(self, reason):
        self._update_button.title = "Update fehlgeschlagen"
        rumps.alert("Update fehlgeschlagen", reason)

    def _restart_after_update(self):
        rumps.alert("Update installiert", "Poker Trainer wird neu gestartet.")
        self.stop_monitoring()
        if BUNDLE_EXE:
            os.execv(BUNDLE_EXE, [BUNDLE_EXE])
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _on_overlay_button(self, tag):
        """Handle overlay button clicks: 1=read now, 2=new hand, 3=what do you think."""
        if not self.companion:
            return
        if tag == 1:
            self.companion.force_read()
        elif tag == 2:
            self.companion.new_hand()
        elif tag == 3:
            self.companion.think_aloud()

    def _listen_hotkey(self):
        """Listen for global hotkey events via Quartz Event Tap."""

        def callback(proxy, event_type, event, refcon):
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            active = self.companion
            if event_type == kCGEventFlagsChanged:
                listener = self.listener
                if listener and keycode == self.cfg.get("talk_keycode", TALK_CODE):
                    if CGEventGetFlags(event) & kCGEventFlagMaskAlternate:
                        listener.press()
                    else:
                        listener.release()
                return event
            if active and self.running:
                if keycode == HOTKEY_CODE:
                    L.info(f"{HOTKEY_NAME} gedrückt: Tisch neu lesen")
                    active.force_read()
                elif keycode == NEWROUND_CODE:
                    L.info(f"{NEWROUND_NAME} gedrückt: neue Hand")
                    active.new_hand()
                elif keycode == THINK_CODE:
                    L.info(f"{THINK_NAME} gedrückt: Was denkst du?")
                    active.think_aloud()
            return event

        mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventFlagsChanged)
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

    def terminate(self):
        L.info("Quit angefordert")
        self.stop_monitoring()
        super().terminate()


def _download_release(tag: str):
    """Download the code of a release and unpack it to UPDATE_DIR."""
    url = f"https://github.com/{REPO}/archive/refs/tags/v{tag}.tar.gz"
    req = urllib.request.Request(url, headers={"User-Agent": "PokerTrainer"})
    tmp = UPDATE_DIR + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    with urllib.request.urlopen(req, timeout=30) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            tar.extractall(tmp, filter="data")
    # GitHub wraps the files in a single folder (poker-trainer-<tag>)
    src = os.path.join(tmp, os.listdir(tmp)[0])
    if not os.path.exists(os.path.join(src, "main.py")):
        raise RuntimeError(f"Kein main.py im Download von v{tag}")
    shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    os.rename(src, UPDATE_DIR)
    shutil.rmtree(tmp, ignore_errors=True)


def _ask_api_key(cfg: dict) -> str:
    """No key configured: take it from the clipboard and store it in the config."""
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    while True:
        clicked = rumps.alert(
            "API Key fehlt",
            "Kopiere den Anthropic API Key (beginnt mit sk-ant-) in die "
            "Zwischenablage und klicke dann auf „Key übernehmen“.",
            ok="Key übernehmen", cancel="Beenden",
        )
        if clicked != 1:
            return ""
        key = NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString) or ""
        if key.strip().startswith("sk-ant-"):
            cfg["api_key"] = key.strip()
            config.save(cfg)
            L.info("API Key aus der Zwischenablage gespeichert")
            return cfg["api_key"]


def _is_poker_trainer(pid: int) -> bool:
    cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                         capture_output=True, text=True).stdout
    return "Poker Trainer.app" in cmd or "main.py" in cmd


def _kill_existing():
    """Kill any existing instance via PID file."""
    if not os.path.exists(PID_FILE):
        return
    try:
        old_pid = int(open(PID_FILE).read().strip())
        # The file outlives quit and reboot: after a restart in place it holds
        # our own PID, later it may point to an unrelated process.
        if old_pid == os.getpid() or not _is_poker_trainer(old_pid):
            return
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

    # A logged-in `claude` is enough, the API key is only the fallback.
    if not brain.find_claude() and not (config.get_api_key(cfg) or _ask_api_key(cfg)):
        L.error("Weder claude noch ANTHROPIC_API_KEY vorhanden!")
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

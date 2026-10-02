"""Settings and region storage for Poker Trainer."""

import json
import os

CONFIG_DIR = os.path.expanduser("~/.poker-trainer")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "api_key": "",
    "crop_region": None,  # {"x": int, "y": int, "w": int, "h": int}
    "overlay_position": None,  # {"x": int, "y": int}
    "change_threshold": 0.05,
    "debounce_seconds": 1.5,
    "capture_interval": 1.0,
    "model": "claude-sonnet-4-6",  # API fallback only
    "backend": "auto",  # "auto" | "cli" (claude -p) | "api"
    "brain_model": "sonnet",
    "watch_model": "haiku",
    "watch_width": 1200,
    "watch_threshold": 0.003,
    "buttons_zone": 0.18,
    "layout": "split",  # "split" (panel next to the table) | "overlay"
    "panel_frame": None,  # {"x": int, "y": int, "w": int, "h": int}
    "strategy": None,  # {"tightness": 1-5, "aggression": 1-5, "bluff": 1-5, "house_rules": str}
    "auto_speak": False,  # True: announce every recommendation, False: speak only when asked
    "voice": None,  # macOS voice name, None = best installed German voice
    "talk_keycode": 61,  # hold to talk, 61 = right Option key
    "record": False,  # save frames and readings to ~/.poker-trainer/sessions for replay
}


def load() -> dict:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            stored = json.load(f)
        merged = {**DEFAULTS, **stored}
        return merged
    return dict(DEFAULTS)


def save(cfg: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def get_api_key(cfg: dict) -> str:
    key = cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    return key


def has_region(cfg: dict) -> bool:
    r = cfg.get("crop_region")
    return r is not None and all(k in r for k in ("x", "y", "w", "h"))

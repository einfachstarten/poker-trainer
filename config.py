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
    "model": "claude-sonnet-4-6",
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

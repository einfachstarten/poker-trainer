"""Decision history: what was recommended, on which numbers, and what the player did."""

from __future__ import annotations

import os
import json
from datetime import datetime
import log

L = log.get("history")

HISTORY_DIR = os.path.expanduser("~/.poker-trainer")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.jsonl")


def log_decision(entry: dict) -> dict:
    """Append one companion decision (state, math, recommendation). Returns the stored entry."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    entry = {"timestamp": datetime.now().isoformat(), **entry}
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    L.debug(f"History: {entry.get('action')} {entry.get('hand')}")
    return entry


def log_hero_action(decision: dict, hero_action: str):
    """Append what the player actually did after a recommendation."""
    entry = {
        "timestamp": datetime.now().isoformat(), "type": "hero_action",
        "hand_no": decision.get("hand_no"), "street": decision.get("street"),
        "recommended": decision.get("action"), "hero_action": hero_action,
        "followed": decision.get("action") == hero_action,
    }
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_session_stats() -> str:
    """Get stats for current session (today)."""
    if not os.path.exists(HISTORY_FILE):
        return "Keine History"

    today = datetime.now().date().isoformat()
    actions = {"FOLD": 0, "CALL": 0, "CHECK": 0, "RAISE": 0, "ALL-IN": 0, "WAIT": 0}
    total = 0
    total_time = 0.0

    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            if entry.get("type") == "hero_action":
                continue
            if entry["timestamp"].startswith(today):
                action = entry.get("action", "?")
                actions[action] = actions.get(action, 0) + 1
                total += 1
                total_time += entry.get("response_time", 0)

    if total == 0:
        return "Heute: keine Analysen"

    avg_time = total_time / total
    parts = [f"{total} Analysen"]
    for a in ("RAISE", "CALL", "FOLD", "CHECK"):
        if actions.get(a, 0) > 0:
            parts.append(f"{a}: {actions[a]}")
    parts.append(f"Ø {avg_time:.1f}s")
    return " | ".join(parts)

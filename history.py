"""Hand history logging."""

from __future__ import annotations

import os
import json
from datetime import datetime
import log

L = log.get("history")

HISTORY_DIR = os.path.expanduser("~/.poker-trainer")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.jsonl")


def log_hand(tip, duration: float):
    """Append a hand analysis to the history file."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": tip.action,
        "amount": tip.amount,
        "reason": tip.reason,
        "hand": tip.hand,
        "board": tip.board,
        "pot_odds": tip.pot_odds,
        "equity": tip.equity,
        "opponents": tip.opponents,
        "response_time": round(duration, 1),
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    L.debug(f"History: {tip.action} {tip.hand}")


def get_session_stats() -> str:
    """Get stats for current session (today)."""
    if not os.path.exists(HISTORY_FILE):
        return "Keine History"

    today = datetime.now().date().isoformat()
    actions = {"FOLD": 0, "CALL": 0, "CHECK": 0, "RAISE": 0, "ALL-IN": 0, "WAIT": 0}
    total = 0
    total_time = 0.0

    with open(HISTORY_FILE) as f:
        for line in f:
            entry = json.loads(line)
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

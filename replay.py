"""Replay recorded sessions through math and strategy, without any LLM call.

Record with "record": true in ~/.poker-trainer/config.json, then:
    .venv/bin/python replay.py                 # latest session, every preset side by side
    .venv/bin/python replay.py <folder> -v     # also list every decision
"""

from __future__ import annotations

import glob
import json
import os
import random
import sys
from collections import Counter

import cards
import equity
from companion import SESSIONS_DIR
from strategy import PRESETS, Situation, StrategyProfile
from table_state import HandTracker, TableState


def decisions(folder: str) -> list[tuple[TableState, Situation]]:
    """Every spot of a recorded session where the player was on turn."""
    tracker, result, rng = HandTracker(), [], random.Random(1)
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        with open(path, encoding="utf-8") as f:
            state = TableState.from_reading(json.load(f))
        if "hero_turn" not in tracker.update(state):
            continue
        eq = equity.equity(state.hero_cards, state.board, state.opponents, iterations=6000, rng=rng)
        result.append((state, Situation(
            street=state.street, hand_class=cards.hand_class(state.hero_cards), equity=eq,
            pot=state.pot, to_call=state.to_call, hero_stack=state.hero_stack,
            opponents=state.opponents, position=state.hero_position,
            raise_level=state.raise_level, big_blind=state.big_blind)))
    return result


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv
    folders = sorted(glob.glob(os.path.join(SESSIONS_DIR, "*")))
    folder = args[0] if args else (folders[-1] if folders else None)
    if not folder or not os.path.isdir(folder):
        sys.exit(f"Keine Aufzeichnung gefunden unter {SESSIONS_DIR}")

    spots = decisions(folder)
    print(f"{folder}: {len(spots)} Entscheidungen")
    if not spots:
        return
    print(f"{'Profil':<20}{'FOLD':>7}{'CHECK':>7}{'CALL':>7}{'RAISE':>7}{'ALL-IN':>8}")
    for name in PRESETS:
        profile = StrategyProfile.from_preset(name)
        counts = Counter(profile.baseline(sit).action for _, sit in spots)
        shares = "".join(f"{round(100 * counts[a] / len(spots)):>{w}}%"
                         for a, w in (("FOLD", 6), ("CHECK", 6), ("CALL", 6), ("RAISE", 6), ("ALL-IN", 7)))
        print(f"{name:<20}{shares}")

    if verbose:
        profile = StrategyProfile()
        for state, sit in spots:
            rec = profile.baseline(sit)
            eq = f"{round(sit.equity * 100)}%" if sit.equity is not None else "-"
            print(f"  {state.street:<8}{cards.pretty_list(state.hero_cards):<8}"
                  f"{cards.pretty_list(state.board):<16}Pot {state.pot} Call {state.to_call} "
                  f"Eq {eq} → {rec.action} {rec.amount or ''} ({rec.note})")


if __name__ == "__main__":
    main()

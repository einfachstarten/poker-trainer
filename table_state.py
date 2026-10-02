"""Structured table state from a vision reading, plus hand tracking across readings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cards

STREETS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}
STREET_NAMES = {"preflop": "Preflop", "flop": "Flop", "turn": "Turn", "river": "River"}
ACTION_KINDS = ("fold", "check", "call", "bet", "raise", "allin")
ACTION_WORDS = {"fold": "steigt aus", "check": "checkt", "call": "geht mit", "bet": "setzt",
                "raise": "erhöht", "allin": "geht All-in"}
HERO_WORDS = {"FOLD": "Du steigst aus.", "CHECK": "Du checkst.", "CALL": "Du gehst mit.",
              "RAISE": "Du erhöhst."}
MIN_ACTIONS_FOR_LABEL = 8


def _num(value) -> float | None:
    """'$2,762' → 2762.0. Comma is a thousands separator, dot a decimal point."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^0-9.]", "", str(value).replace(",", ""))
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _action_kind(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.lower().replace("-", "").replace(" ", "")
    for kind in ("allin", "fold", "check", "call", "raise", "bet"):
        if kind in text:
            return kind
    return None


@dataclass
class Player:
    name: str
    stack: float | None = None
    in_hand: bool = True
    last_action: str | None = None
    dealer: bool = False


@dataclass
class TableState:
    hero_cards: list[str] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    street: str = "preflop"
    pot: float | None = None
    to_call: float = 0.0
    hero_stack: float | None = None
    hero_to_act: bool = False
    buttons: list[str] = field(default_factory=list)
    players: list[Player] = field(default_factory=list)
    hero_position: str | None = None
    big_blind: float | None = None
    facing_raise: bool | None = None
    opponents_hint: int | None = None  # quick readings count the opponents instead of listing them
    winner: str | None = None  # who took the pot, "Du" for the hero; only once a hand is decided
    showdown: list[dict] = field(default_factory=list)  # [{"name": ..., "cards": [...]}]
    valid: bool = True

    @classmethod
    def from_reading(cls, data) -> "TableState | None":
        """Build a state from the vision model's JSON. None if it is not a reading at all."""
        if not isinstance(data, dict):
            return None
        hero = cards.normalize_cards(data.get("hero_cards"))
        board = cards.normalize_cards(data.get("board"))
        everything = hero + board
        valid = (len(hero) in (0, 2) and len(board) in STREETS
                 and len(set(everything)) == len(everything))

        players = []
        for p in data.get("players") or []:
            if not isinstance(p, dict) or not p.get("name"):
                continue
            players.append(Player(
                name=str(p["name"]), stack=_num(p.get("stack")),
                in_hand=bool(p.get("in_hand", True)),
                last_action=_action_kind(p.get("last_action")),
                dealer=bool(p.get("dealer", False)),
            ))

        # Only the button is read off the table. Other positions need the seat order,
        # which a single screenshot reading does not give reliably.
        position = "BTN" if data.get("hero_dealer") is True else None
        winner = data.get("winner")
        if isinstance(winner, str) and winner.strip():
            winner = "Du" if winner.strip().lower() in ("hero", "you", "du", "ich") else winner.strip()
        else:
            winner = None
        showdown = []
        for shown in data.get("showdown") or []:
            if isinstance(shown, dict) and shown.get("name"):
                shown_cards = cards.normalize_cards(shown.get("cards"))
                if len(shown_cards) == 2:
                    showdown.append({"name": str(shown["name"]), "cards": shown_cards})
        facing = data.get("facing_raise")
        return cls(
            hero_cards=hero, board=board, street=STREETS.get(len(board), "preflop"),
            pot=_num(data.get("pot")), to_call=_num(data.get("to_call")) or 0.0,
            hero_stack=_num(data.get("hero_stack")), hero_to_act=bool(data.get("hero_to_act")),
            buttons=[str(b) for b in data.get("buttons") or []], players=players,
            hero_position=position,
            big_blind=_num(data.get("big_blind")),
            facing_raise=facing if isinstance(facing, bool) else None,
            opponents_hint=int(hint) if (hint := _num(data.get("opponents_in_hand"))) else None,
            winner=winner, showdown=showdown,
            valid=valid,
        )

    @property
    def opponents(self) -> int:
        if not self.players and self.opponents_hint:
            return max(1, self.opponents_hint)
        return max(1, sum(1 for p in self.players if p.in_hand))

    @property
    def actionable(self) -> bool:
        return self.valid and self.hero_to_act and len(self.hero_cards) == 2

    @property
    def raise_level(self) -> int | None:
        """Preflop only: 0 unopened or limped, 1 facing a raise, 2 facing a re-raise."""
        if self.street != "preflop":
            return None
        if self.big_blind:
            if self.to_call <= self.big_blind:
                return 0
            return 1 if self.to_call <= self.big_blind * 5 else 2
        if self.facing_raise is None:
            return None
        return 1 if self.facing_raise else 0

    def key(self) -> tuple:
        return (tuple(self.hero_cards), tuple(self.board), self.pot, self.to_call, self.hero_to_act)


class HandTracker:
    """Follows one table over time: hand boundaries, street changes, opponent tendencies."""

    def __init__(self):
        self.hand_no = 0
        self.opponents: dict[str, dict] = {}
        self.timeline: list[dict] = []
        self.players: list[Player] = []  # last full reading of the table
        self.state: TableState | None = None
        self.hand_log: list[str] = []  # everything about the running hand, oldest first
        self._news: list[str] = []
        self._start_stack: float | None = None
        self._winner: str | None = None
        self._showdown: list[dict] = []
        self._finished: dict | None = None
        self._cards: list[str] | None = None
        self._board: list[str] = []
        self._street: str | None = None
        self._force_new = False
        self._last_turn_key = None
        self._seen_actions: set = set()
        self._hand_players: set = set()
        self._pending_turn: TableState | None = None
        self._hero_action: str | None = None

    def reset_hand(self):
        """Manual 'new hand' (F2): the next reading starts a hand even with the same cards."""
        self._force_new = True

    def update(self, state: TableState | None) -> list[str]:
        if state is None or not state.valid:
            return []
        events = []
        if len(state.hero_cards) == 2 and self._is_new_hand(state):
            self._resolve_hero_action(state, hand_ended=True)
            if self.hand_no:
                self._finish_hand(state)
            self.hand_no += 1
            self.hand_log = []
            self._start_stack = state.hero_stack
            self._winner, self._showdown = None, []
            self._cards = list(state.hero_cards)
            self._street = None
            self._last_turn_key = None
            self._force_new = False
            self._seen_actions.clear()
            self._hand_players.clear()
            self.timeline = []
            events.append("new_hand")
            self._tell(f"Neue Hand. Du hast {cards.pretty_list(state.hero_cards)}.")
        elif len(state.hero_cards) == 2:
            self._cards = list(state.hero_cards)  # corrected misread within the same hand
        else:
            self._resolve_hero_action(state, hand_ended=False)

        if self.hand_no and state.street != self._street:
            if self._street is not None:
                events.append("street")
                if state.board:
                    fresh = state.board[len(self._board):] if state.street != "flop" else state.board
                    self._tell(f"{STREET_NAMES[state.street]}: {cards.pretty_list(fresh)}")
            self._street = state.street
        self._board = list(state.board)

        self._count_opponents(state)
        self._resolve_hero_action(state, hand_ended=False)
        if state.actionable and state.key() != self._last_turn_key:
            self._last_turn_key = state.key()
            self._pending_turn = state
            events.append("hero_turn")
            price = f"Mitgehen kostet {fmt_amount(state.to_call)}." if state.to_call else "Check ist gratis."
            self._tell(f"Du bist dran. {price}")
        self._note_result(state)

        entry = {"street": state.street, "pot": state.pot, "to_call": state.to_call,
                 "actions": {p.name: p.last_action for p in state.players if p.last_action}}
        if not self.timeline or self.timeline[-1] != entry:
            self.timeline.append(entry)
        self.state = state
        return events

    def _is_new_hand(self, state: TableState) -> bool:
        if self._force_new or self._cards is None:
            return True
        if state.hero_cards == self._cards:
            # same hole cards: only a board that went back to empty means a new deal
            return bool(self._board) and not state.board
        # different cards on a board that continues the old one is a corrected misread
        continues = bool(state.board) and state.board[:len(self._board)] == self._board
        return not continues

    def _count_opponents(self, state: TableState):
        if state.players:
            self.players = state.players
        for p in state.players:
            stats = self.opponents.setdefault(p.name, {"hands": 0, **{k: 0 for k in ACTION_KINDS}})
            if p.name not in self._hand_players:
                self._hand_players.add(p.name)
                stats["hands"] += 1
            if p.last_action:
                key = (self.hand_no, state.street, p.name, p.last_action)
                if key not in self._seen_actions:
                    self._seen_actions.add(key)
                    stats[p.last_action] += 1
                    self._tell(f"{p.name} {ACTION_WORDS[p.last_action]}.")

    def _resolve_hero_action(self, state: TableState, hand_ended: bool):
        """Infer what the hero did after the last advised turn from the stack change."""
        turn = self._pending_turn
        if turn is None or state.key() == turn.key():
            return
        if state.actionable and not hand_ended and state.street == turn.street \
                and state.to_call == turn.to_call:
            return  # still the same decision
        action = None
        known = turn.hero_stack is not None and state.hero_stack is not None
        paid = turn.hero_stack - state.hero_stack if known else None
        if known and not hand_ended:
            if paid > turn.to_call + 0.01:
                action = "RAISE"
            elif turn.to_call and abs(paid - turn.to_call) <= 0.01:
                action = "CALL"
            elif abs(paid) <= 0.01:
                if not state.hero_cards and turn.to_call:
                    action = "FOLD"
                elif not turn.to_call:
                    action = "CHECK"
        elif hand_ended and known:
            # The next deal shows the stack after the whole hand: unchanged means the hero got out,
            # exactly the call amount less means he called and lost. Anything else stays open.
            if abs(paid) <= 0.01:
                action = "FOLD" if turn.to_call else "CHECK"
            elif turn.to_call and abs(paid - turn.to_call) <= 0.01:
                action = "CALL"
            elif turn.to_call:
                self._tell("Du bist in der Hand geblieben.")
        elif hand_ended and turn.to_call:
            action = "FOLD"
        if action or hand_ended:
            self._hero_action = action
            self._pending_turn = None
            if action:
                self._tell(HERO_WORDS[action])

    def _tell(self, line: str):
        self._news.append(line)
        self.hand_log.append(line)

    def note(self, line: str):
        """Add a line to the hand's log that is not table news, e.g. what was recommended."""
        self.hand_log.append(line)

    def _note_result(self, state: TableState):
        for shown in state.showdown:
            if shown not in self._showdown:
                self._showdown.append(shown)
                self._tell(f"{shown['name']} zeigt {cards.pretty_list(shown['cards'])}.")
        if state.winner and state.winner != self._winner:
            self._winner = state.winner
            self._tell("Du gewinnst den Pot." if state.winner == "Du" else f"{state.winner} gewinnt den Pot.")

    def _finish_hand(self, next_state: TableState):
        """Close the record of the hand that just ended. The stack is read off the next deal,
        so the difference can include a blind the hero has already posted there."""
        delta = None
        if self._start_stack is not None and next_state.hero_stack is not None:
            delta = next_state.hero_stack - self._start_stack
        self._finished = {
            "hand_no": self.hand_no, "cards": list(self._cards or []), "board": list(self._board),
            "log": list(self.hand_log), "start_stack": self._start_stack,
            "end_stack": next_state.hero_stack, "delta": delta,
            "winner": self._winner, "showdown": list(self._showdown),
        }

    def pop_finished_hand(self) -> dict | None:
        finished, self._finished = self._finished, None
        return finished

    def pop_news(self) -> list[str]:
        """What happened since the last call, in plain words, oldest first."""
        news, self._news = self._news, []
        return news

    def pop_hero_action(self) -> str | None:
        action, self._hero_action = self._hero_action, None
        return action

    def opponent_label(self, name: str) -> str:
        stats = self.opponents.get(name)
        total = sum(stats[k] for k in ACTION_KINDS) if stats else 0
        if total < MIN_ACTIONS_FOR_LABEL:
            return "zu wenig Daten"
        tight = "tight" if stats["fold"] / total >= 0.5 else "loose"
        pushy = (stats["bet"] + stats["raise"] + stats["allin"]) / total >= 0.3
        return f"{tight}-{'aggressiv' if pushy else 'passiv'}"

    def opponents_view(self) -> list[dict]:
        """Opponents at the table right now, for the panel and the LLM."""
        view = []
        for p in self.players:
            stats = self.opponents.get(p.name, {})
            counts = ", ".join(f"{stats[k]}x {k}" for k in ACTION_KINDS if stats.get(k))
            view.append({"name": p.name, "label": self.opponent_label(p.name),
                         "hands": stats.get("hands", 0), "counts": counts,
                         "in_hand": p.in_hand, "last_action": p.last_action})
        return view

    def summary(self) -> str:
        """Compact text of the current hand for the LLM."""
        if not self.state or not self.hand_no:
            return "Noch keine Hand erkannt."
        s = self.state
        lines = [f"Hand {self.hand_no}, {STREET_NAMES[s.street]}. "
                 f"Hero {cards.pretty_list(s.hero_cards) or '-'}, Board {cards.pretty_list(s.board) or '-'}, "
                 f"Pot {fmt_amount(s.pot)}, zu zahlen {fmt_amount(s.to_call)}."]
        by_street: dict[str, dict] = {}
        for entry in self.timeline:
            by_street.setdefault(entry["street"], {}).update(entry["actions"])
        for street, actions in by_street.items():
            if actions:
                lines.append(f"{STREET_NAMES[street]}: " + ", ".join(f"{n} {a}" for n, a in actions.items()))
        notes = [f"{o['name']} ({o['label']}, {o['counts']})" for o in self.opponents_view()
                 if o["in_hand"] and o["counts"]]
        if notes:
            lines.append("Gegner bisher: " + "; ".join(notes))
        return "\n".join(lines)


def fmt_amount(value: float | None) -> str:
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"

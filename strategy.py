"""Adjustable strategy profile: three dials become concrete thresholds and guard rails.

The numbers below are starting values to tune against recorded sessions, not poker truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import equity as eq

ACTIONS = ("FOLD", "CHECK", "CALL", "RAISE", "ALL-IN")

# dial value 1..5 → threshold
_VALUE_BET_HU = {1: 0.80, 2: 0.72, 3: 0.65, 4: 0.58, 5: 0.50}
_ALL_IN_HU = {1: 0.88, 2: 0.82, 3: 0.76, 4: 0.68, 5: 0.60}
_RAISE_SHARE = {1: 0.25, 2: 0.40, 3: 0.60, 4: 0.80, 5: 1.00}
_THREE_BET_SHARE = {1: 0.08, 2: 0.12, 3: 0.18, 4: 0.25, 5: 0.35}
_BET_FRACTION = {1: 0.33, 2: 0.50, 3: 0.60, 4: 0.75, 5: 1.00}
_MAX_BET_FRACTION = {1: 0.50, 2: 0.66, 3: 0.75, 4: 1.00, 5: 1.50}
_OPEN_RANGE = {1: 0.10, 2: 0.16, 3: 0.22, 4: 0.30, 5: 0.40}
_CALL_MARGIN = {1: 0.10, 2: 0.06, 3: 0.03, 4: 0.00, 5: -0.03}
_BLUFF_SLACK = {1: 0.00, 2: 0.03, 3: 0.10, 4: 0.20, 5: 1.00}
_POSITION_FACTOR = {"UTG": 0.7, "EP": 0.7, "MP": 0.85, "CO": 1.15, "BTN": 1.3, "SB": 0.9, "BB": 1.0}

PRESETS = {
    "Moderat aggressiv": (2, 3, 2),
    "Tight-Aggressive": (2, 4, 2),
    "Loose-Aggressive": (4, 5, 4),
    "Konservativ": (1, 1, 1),
    "Balanced": (3, 3, 3),
}
DEFAULT_PRESET = "Moderat aggressiv"
_LEGACY = {"TAG": "Tight-Aggressive", "LAG": "Loose-Aggressive",
           "Conservative": "Konservativ", "Balanced": "Balanced"}


@dataclass
class Situation:
    street: str
    hand_class: str | None
    equity: float | None
    pot: float | None
    to_call: float
    hero_stack: float | None
    opponents: int
    position: str | None = None
    raise_level: int | None = None  # preflop: 0 unopened/limped, 1 raise, 2 re-raise; None unknown
    big_blind: float | None = None


@dataclass
class Recommendation:
    action: str
    amount: float | None = None
    clamped: bool = False
    note: str = ""


def _dial(value, default: int) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return default


def _money(value: float) -> float:
    return float(round(value)) if value >= 10 else round(value, 2)


def fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _pct(value: float) -> str:
    return f"{round(value * 100)} %"


@dataclass
class StrategyProfile:
    tightness: int = 2   # Handauswahl: 1 tight ... 5 loose
    aggression: int = 3  # 1 passiv ... 5 aggressiv
    bluff: int = 2       # 1 nie ... 5 oft
    house_rules: str = ""

    @property
    def name(self) -> str:
        dials = (self.tightness, self.aggression, self.bluff)
        for name, preset in PRESETS.items():
            if preset == dials:
                return name
        return "Eigene Einstellung"

    @classmethod
    def from_dict(cls, data: dict | None) -> "StrategyProfile":
        data = data or {}
        return cls(
            tightness=_dial(data.get("tightness"), 2),
            aggression=_dial(data.get("aggression"), 3),
            bluff=_dial(data.get("bluff"), 2),
            house_rules=str(data.get("house_rules") or ""),
        )

    @classmethod
    def from_preset(cls, name: str) -> "StrategyProfile":
        t, a, b = PRESETS.get(name, PRESETS[DEFAULT_PRESET])
        return cls(tightness=t, aggression=a, bluff=b)

    @classmethod
    def from_legacy(cls, play_style: str | None) -> "StrategyProfile":
        """Maps the old `play_style` config value (TAG, LAG, ...) to a preset."""
        return cls.from_preset(_LEGACY.get(play_style or "", DEFAULT_PRESET))

    def to_dict(self) -> dict:
        return asdict(self)

    def thresholds(self, opponents: int = 1, position: str | None = None) -> dict:
        """Concrete numbers for this profile. Equity thresholds scale with the number of opponents."""
        fair = 1.0 / (max(1, opponents) + 1)

        def scaled(heads_up: float) -> float:
            return fair + (heads_up - 0.5) / 0.5 * (1.0 - fair)

        open_range = min(1.0, _OPEN_RANGE[self.tightness] * _POSITION_FACTOR.get(position or "", 1.0))
        value_hu = _VALUE_BET_HU[self.aggression]
        return {
            "value_bet": scaled(value_hu),
            "raise_vs_bet": scaled(min(0.95, value_hu + 0.07)),
            "all_in": scaled(_ALL_IN_HU[self.aggression]),
            "call_margin": _CALL_MARGIN[self.tightness],
            "bluff_slack": _BLUFF_SLACK[self.bluff],
            "bet_fraction": _BET_FRACTION[self.aggression],
            "max_bet_fraction": _MAX_BET_FRACTION[self.aggression],
            "open_range": open_range,
            "raise_range": open_range * _RAISE_SHARE[self.aggression],
            "three_bet_range": open_range * _THREE_BET_SHARE[self.aggression],
            "call_raise_range": open_range * 0.55,
        }

    # --- baseline: what the math plus the profile say, without any LLM ---

    def baseline(self, sit: Situation) -> Recommendation:
        if sit.street == "preflop":
            return self._baseline_preflop(sit)
        return self._baseline_postflop(sit)

    def _preflop_ranges(self, sit: Situation) -> tuple[float, float, int]:
        """(raise range, call range, raise level) for the current preflop spot."""
        th = self.thresholds(sit.opponents, sit.position)
        level = sit.raise_level
        if level is None:
            # Without blind info a required call is treated as facing a raise: the careful reading.
            level = 1 if sit.to_call else 0
        if level <= 0:
            return th["raise_range"], th["open_range"], 0
        if level == 1:
            return th["three_bet_range"], th["call_raise_range"], 1
        return th["open_range"] * 0.06, th["open_range"] * 0.15, 2

    def _baseline_preflop(self, sit: Situation) -> Recommendation:
        pct = eq.preflop_percentile(sit.hand_class)
        if pct is None:
            return Recommendation("?", note="Karten nicht erkannt")
        raise_range, call_range, level = self._preflop_ranges(sit)
        hand = f"{sit.hand_class} gehört zu den besten {_pct(pct)}"
        if pct <= raise_range:
            amount = self._preflop_raise_size(sit, level)
            return self._sized_raise(sit, amount, f"{hand}, Raise-Range {_pct(raise_range)}")
        if not sit.to_call:
            return Recommendation("CHECK", note=f"{hand}, kein Raise, Check ist gratis")
        if pct <= call_range:
            return Recommendation("CALL", _money(sit.to_call), note=f"{hand}, Call-Range {_pct(call_range)}")
        return Recommendation("FOLD", note=f"{hand}, spielbar wären {_pct(call_range)}")

    def _preflop_raise_size(self, sit: Situation, level: int) -> float:
        if level == 0:
            if sit.big_blind:
                return sit.big_blind * (2.5 if self.aggression <= 2 else 3.0)
            return max((sit.to_call or 0) * 3.0, (sit.pot or 0) * 1.5)
        return (sit.to_call or 0) * (3.0 if level == 1 else 2.5)

    def _baseline_postflop(self, sit: Situation) -> Recommendation:
        if sit.equity is None:
            return Recommendation("?", note="Karten nicht erkannt")
        th = self.thresholds(sit.opponents, sit.position)
        mine = f"Equity {_pct(sit.equity)}"
        if not sit.to_call:
            if sit.equity >= th["value_bet"] and sit.pot:
                return self._sized_raise(sit, sit.pot * th["bet_fraction"],
                                         f"{mine}, Value Bet ab {_pct(th['value_bet'])}")
            return Recommendation("CHECK", note=f"{mine}, Value Bet erst ab {_pct(th['value_bet'])}")
        if sit.equity >= th["raise_vs_bet"]:
            return self._sized_raise(sit, sit.to_call * 3.0, f"{mine}, Raise ab {_pct(th['raise_vs_bet'])}")
        required = eq.required_equity(sit.pot, sit.to_call)
        if required is None:
            return Recommendation("?", note="Pot nicht erkannt")
        need = required + th["call_margin"]
        if sit.equity >= need:
            return Recommendation("CALL", _money(sit.to_call), note=f"{mine}, nötig {_pct(need)}")
        return Recommendation("FOLD", note=f"{mine}, nötig {_pct(need)}")

    def _sized_raise(self, sit: Situation, amount: float, note: str) -> Recommendation:
        """A raise that would take the whole stack only stays if an all-in is allowed."""
        if sit.hero_stack and amount >= sit.hero_stack:
            if self.all_in_allowed(sit):
                return Recommendation("ALL-IN", _money(sit.hero_stack), note=note)
            if sit.to_call:
                return Recommendation("CALL", _money(min(sit.to_call, sit.hero_stack)), note=note)
            return Recommendation("CHECK", note=note)
        return Recommendation("RAISE", _money(amount), note=note)

    # --- guard rails for what the LLM proposes ---

    def raise_allowed(self, sit: Situation) -> bool:
        if sit.street == "preflop":
            pct = eq.preflop_percentile(sit.hand_class)
            if pct is None:
                return False
            raise_range, _, _ = self._preflop_ranges(sit)
            return pct <= raise_range * 1.25
        if sit.equity is None:
            return False
        th = self.thresholds(sit.opponents, sit.position)
        bar = th["raise_vs_bet"] if sit.to_call else th["value_bet"]
        return sit.equity >= bar - th["bluff_slack"]

    def all_in_allowed(self, sit: Situation) -> bool:
        if sit.street == "preflop":
            pct = eq.preflop_percentile(sit.hand_class)
            th = self.thresholds(sit.opponents, sit.position)
            return pct is not None and pct <= th["open_range"] * 0.06 * (1 + self.aggression / 5)
        if sit.equity is None:
            return False
        th = self.thresholds(sit.opponents, sit.position)
        if sit.equity >= th["all_in"]:
            return True
        short = bool(sit.hero_stack and sit.pot and sit.hero_stack <= sit.pot)
        return short and self.raise_allowed(sit)

    def _call_allowed(self, sit: Situation) -> bool:
        if sit.street == "preflop":
            pct = eq.preflop_percentile(sit.hand_class)
            if pct is None:
                return False
            _, call_range, _ = self._preflop_ranges(sit)
            return pct <= call_range * 1.3
        required = eq.required_equity(sit.pot, sit.to_call)
        if sit.equity is None or required is None:
            return False
        return sit.equity >= required + self.thresholds(sit.opponents)["call_margin"] - 0.05

    def _max_raise(self, sit: Situation) -> float | None:
        if sit.pot is None or sit.street == "preflop":
            return None
        fraction = self.thresholds(sit.opponents)["max_bet_fraction"]
        if not sit.to_call:
            return sit.pot * fraction
        return sit.to_call + (sit.pot + sit.to_call) * fraction

    def clamp(self, rec: Recommendation, sit: Situation) -> Recommendation:
        """Cap a proposed action to what the profile allows. Sets `clamped` when it had to step in."""
        base = self.baseline(sit)
        if base.action == "?":
            return rec
        action = (rec.action or "").upper()

        def capped(reason: str) -> Recommendation:
            return Recommendation(base.action, base.amount, True, reason)

        if action in ("FOLD", "CALL") and not sit.to_call:
            return Recommendation("CHECK", None, action == "FOLD", "Check ist gratis")
        if action == "CHECK":
            return Recommendation("CHECK") if not sit.to_call else capped("Check nicht möglich")
        if action == "FOLD":
            return Recommendation("FOLD")
        if action == "CALL":
            if self._call_allowed(sit):
                return Recommendation("CALL", _money(sit.to_call))
            return capped("Call zu teuer für diese Strategie")
        if action == "ALL-IN":
            if self.all_in_allowed(sit):
                return Recommendation("ALL-IN", _money(sit.hero_stack) if sit.hero_stack else None)
            if self.raise_allowed(sit) and base.action == "RAISE":
                return Recommendation("RAISE", base.amount, True, "All-in zu riskant für diese Strategie")
            return capped("All-in zu riskant für diese Strategie")
        if action == "RAISE":
            if not self.raise_allowed(sit):
                return capped("Raise zu aggressiv für diese Strategie")
            amount = rec.amount
            if amount is None:
                return Recommendation("RAISE", base.amount if base.action == "RAISE" else None)
            limit = self._max_raise(sit)
            if limit is not None and amount > limit:
                return Recommendation("RAISE", _money(limit), True, "Betrag auf Strategie-Maximum gekürzt")
            if sit.hero_stack and amount >= sit.hero_stack and not self.all_in_allowed(sit):
                return capped("All-in zu riskant für diese Strategie")
            return Recommendation("RAISE", _money(amount))
        return capped("Empfehlung nicht lesbar")

    # --- looking ahead while the others act ---

    def plan(self, sit: Situation) -> str:
        """What to do when the turn comes, in plain words. Empty without readable cards."""
        if sit.street == "preflop":
            pct = eq.preflop_percentile(sit.hand_class)
            if pct is None:
                return ""
            th = self.thresholds(sit.opponents, sit.position)
            if pct <= th["three_bet_range"]:
                return "Starke Hand. Erhöhen, auch wenn schon jemand erhöht hat."
            if pct <= th["raise_range"]:
                return "Gute Hand. Erhöhen, wenn vor dir niemand erhöht hat, sonst mitgehen."
            if pct <= th["open_range"]:
                return "Spielbare Hand. Mitgehen, solange es billig bleibt. Erhöht jemand: aussteigen."
            return "Schwache Hand. Check, wenn es gratis ist. Setzt jemand: aussteigen."
        if sit.equity is None:
            return ""
        th = self.thresholds(sit.opponents, sit.position)
        if sit.equity >= th["value_bet"] and sit.pot:
            free = f"Bet {fmt(_money(sit.pot * th['bet_fraction']))}"
        else:
            free = "Check"
        share = sit.equity - th["call_margin"]
        limit = sit.pot * share / (1 - share) if sit.pot and 0 < share < 1 else 0
        if limit >= sit.pot * 0.1:  # a price below a tenth of the pot is no real call
            priced = f"Setzt jemand: mitgehen bis etwa {fmt(_money(limit))}, darüber aussteigen."
        else:
            priced = "Setzt jemand: aussteigen."
        return f"Wenn niemand setzt: {free}. {priced}"

    # --- text for the LLM ---

    def describe(self, sit: Situation | None = None) -> str:
        lines = [f"Strategie: {self.name} (Handauswahl {self.tightness}/5, "
                 f"Aggression {self.aggression}/5, Bluffs {self.bluff}/5)."]
        th = self.thresholds(sit.opponents if sit else 1, sit.position if sit else None)
        lines.append(
            f"Leitplanken: Value Bet ab {_pct(th['value_bet'])} Equity, Raise gegen einen Bet ab "
            f"{_pct(th['raise_vs_bet'])}, All-in ab {_pct(th['all_in'])}, Call ab benötigter Equity "
            f"plus {round(th['call_margin'] * 100)} Punkte. Preflop spielbar: beste {_pct(th['open_range'])} "
            f"der Hände, Raise mit den besten {_pct(th['raise_range'])}, gegen einen Raise nur die besten "
            f"{_pct(th['call_raise_range'])}.")
        if self.house_rules:
            lines.append(f"Hausregeln: {self.house_rules}")
        return "\n".join(lines)

"""The companion itself: watches the table, does the math, talks to Claude, feeds panel and voice."""

from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime

import cards
import equity
import history
import log
from speech_text import MarkerStream, parse_markers
from strategy import PRESETS, Recommendation, Situation, StrategyProfile
from table_state import STREET_NAMES, HandTracker, TableState, fmt_amount
from watcher import Watcher

L = log.get("companion")

SESSIONS_DIR = os.path.expanduser("~/.poker-trainer/sessions")
TRANSCRIPT_LINES = 40
HANDS_PER_VOICE_SESSION = 15


class Companion:
    def __init__(self, cfg: dict, backend, view, speaker, save_cfg=None):
        """view needs render(model: dict). save_cfg(cfg) persists settings changed at runtime."""
        self.cfg = cfg
        self.backend = backend
        self.view = view
        self.speaker = speaker
        self._save_cfg = save_cfg or (lambda cfg: None)
        if cfg.get("strategy"):
            self.profile = StrategyProfile.from_dict(cfg["strategy"])
        else:
            # first start after the update: everyone begins on the moderate default
            self.profile = StrategyProfile()
        self.talkativeness = cfg.get("talkativeness", "normal")
        self.tracker = HandTracker()
        self.watcher = Watcher(
            lambda: self.cfg["crop_region"], self._on_frame,
            interval=cfg.get("capture_interval", 0.5),
            threshold=cfg.get("watch_threshold", 0.003),
            buttons_zone=cfg.get("buttons_zone", 0.18),
        )
        self._lock = threading.Lock()
        self._advice_gen = 0
        self._talk_gen = 0
        self._retried = False
        self._listening = False
        self._hands_in_voice_session = 0
        self._frame_no = 0
        self._last_img = None
        self._last_decision: dict | None = None
        self._transcript: list[dict] = []
        self._model: dict = {"status": "Startet", "backend": backend.name}

    # --- lifecycle and controls ---

    def start(self):
        self._update(status="Schaue auf den Tisch", headline="Warte auf den Tisch")
        self.watcher.start()

    def stop(self):
        self.watcher.stop()
        self._advice_gen += 1
        self.speaker.stop()
        self.backend.close()

    def force_read(self):
        self.watcher.force()

    def new_hand(self):
        self.tracker.reset_hand()
        self.watcher.force()

    def toggle_mute(self) -> bool:
        self.speaker.set_muted(not self.speaker.muted)
        self._update()
        return self.speaker.muted

    def set_strategy(self, changes: dict):
        self.profile = StrategyProfile.from_dict({**self.profile.to_dict(), **changes})
        self.cfg["strategy"] = self.profile.to_dict()
        self._save_cfg(self.cfg)
        L.info(f"Strategie: {self.profile.name} {self.profile.to_dict()}")
        state = self.tracker.state
        if state and state.actionable:
            # the dials moved while a decision is open: show what they mean right away
            self._show_baseline(state, self._situation(state, self._model.get("equity")))
        else:
            self._update()

    def cycle_preset(self) -> str:
        names = list(PRESETS)
        current = self.profile.name
        nxt = names[(names.index(current) + 1) % len(names)] if current in names else names[0]
        t, a, b = PRESETS[nxt]
        self.set_strategy({"tightness": t, "aggression": a, "bluff": b})
        return nxt

    def on_view_message(self, message: dict):
        """Events from the panel page: slider moved, question typed."""
        if message.get("type") == "strategy":
            self.set_strategy({k: message.get(k) for k in ("tightness", "aggression", "bluff")})
        elif message.get("type") == "ask" and message.get("text"):
            self.ask(str(message["text"]))

    def set_listening(self, state: str):
        """Push-to-talk state: 'listening', 'transcribing' or 'idle'. Talking cuts the coach off."""
        if state == "listening":
            self._listening = True
            self._talk_gen += 1
            self.speaker.stop()
            self._update(status="Höre zu")
        elif state == "transcribing":
            self._update(status="Verstehe dich")
        else:
            self._listening = False
            self._update(status="Schaue auf den Tisch")

    def ask(self, text: str):
        """A question from the player, typed or spoken."""
        threading.Thread(target=self._converse, args=(text,), daemon=True).start()

    # --- watching ---

    def _on_frame(self, img, reason: str):
        self._update(status="Lese Tisch")
        t0 = time.time()
        try:
            reading = self.backend.read_table(img)
        except Exception as e:
            L.error(f"Tisch-Lesung fehlgeschlagen: {e}")
            self._update(status="Claude nicht erreichbar")
            return
        state = TableState.from_reading(reading)
        L.info(f"Lesung ({reason}) nach {time.time() - t0:.1f}s: {reading}")
        self._record(img, reading)
        if state is None or not state.valid:
            self._update(status="Tisch nicht lesbar")
            if not self._retried:  # one more look, card misreads are usually one-offs
                self._retried = True
                self.watcher.force()
            return
        self._retried = False
        self._last_img = img

        events = self.tracker.update(state)
        hero_action = self.tracker.pop_hero_action()
        if hero_action and self._last_decision:
            history.log_hero_action(self._last_decision, hero_action)
            self._last_decision = None
        if "new_hand" in events:
            self._on_new_hand()

        eq = self._equity(state)
        self._show_table(state, eq)
        if "hero_turn" in events:
            threading.Thread(target=self._advise, args=(state, eq), daemon=True).start()
        elif not state.actionable:
            self._advice_gen += 1  # whatever was being said about the old decision is stale
            headline = "Gegner sind dran" if state.hero_cards else "Warte auf die nächste Hand"
            self._update(action=None, amount=None, clamp_note="", source="", headline=headline,
                         status="Schaue auf den Tisch")

    def _on_new_hand(self):
        self._advice_gen += 1
        self.backend.new_hand()
        self._hands_in_voice_session += 1
        if self._hands_in_voice_session >= HANDS_PER_VOICE_SESSION:
            self._hands_in_voice_session = 0
            notes = "; ".join(f"{o['name']}: {o['label']} ({o['counts']})"
                              for o in self.tracker.opponents_view() if o["counts"])
            self.backend.reset_conversation(f"Gegner bisher: {notes}" if notes else "")
        self._update(action=None, amount=None, clamp_note="", source="", why="",
                     headline="Neue Hand")

    def _equity(self, state: TableState) -> float | None:
        if len(state.hero_cards) != 2:
            return None
        # seeded per situation, so reading the same table twice shows the same number
        seed = " ".join(state.hero_cards + state.board) + f" {state.opponents}"
        return equity.equity(state.hero_cards, state.board, state.opponents,
                             iterations=self.cfg.get("equity_iterations", 6000),
                             rng=random.Random(seed))

    def _situation(self, state: TableState, eq: float | None) -> Situation:
        return Situation(
            street=state.street, hand_class=cards.hand_class(state.hero_cards), equity=eq,
            pot=state.pot, to_call=state.to_call, hero_stack=state.hero_stack,
            opponents=state.opponents, position=state.hero_position,
            raise_level=state.raise_level, big_blind=state.big_blind,
        )

    # --- advising ---

    def _show_baseline(self, state: TableState, sit: Situation) -> Recommendation:
        base = self.profile.baseline(sit)
        if base.action == "?":
            self._update(action=None, headline="Karten nicht erkannt", why=base.note, status="Du bist dran")
        else:
            self._update(action=base.action, amount=_amount(base), source="Basis: Mathe und Strategie",
                         clamp_note="", why=base.note, headline="", status="Du bist dran")
        return base

    def _advise(self, state: TableState, eq: float | None):
        self._advice_gen += 1
        gen = self._advice_gen
        t0 = time.time()
        sit = self._situation(state, eq)
        base = self._show_baseline(state, sit)
        final = base
        coach: list[str] = []
        stream = MarkerStream()

        def handle(items):
            nonlocal final
            for kind, text in items:
                if kind == "marker":
                    rec = parse_markers([text]).get("recommendation")
                    if rec and base.action != "?":
                        final = self.profile.clamp(Recommendation(*rec), sit)
                        self._update(action=final.action, amount=_amount(final), source="Coach",
                                     clamp_note="begrenzt durch Strategie" if final.clamped else "")
                        if final.clamped:
                            self._say(_spoken(final))
                elif gen == self._advice_gen:
                    coach.append(text)
                    self._update(why=" ".join(coach))
                    if not final.clamped:
                        self._say(text)

        try:
            self.backend.ask(self._decision_prompt(state, sit, base), None,
                             on_delta=lambda d: handle(stream.feed(d)),
                             cancelled=lambda: gen != self._advice_gen)
            handle(stream.flush())
        except Exception as e:
            L.error(f"Coach nicht erreichbar, Basis-Empfehlung bleibt: {e}")
            if gen == self._advice_gen and base.action != "?":
                self._say(_spoken(base))
        if gen != self._advice_gen:
            return

        if final.clamped:
            self._update(why=f"{final.note}. Der Coach wollte: {' '.join(coach)}")
        if coach:
            self._add_line("coach", " ".join(coach))
        self._last_decision = history.log_decision({
            "hand_no": self.tracker.hand_no, "street": state.street,
            "hand": cards.pretty_list(state.hero_cards), "board": cards.pretty_list(state.board),
            "pot": state.pot, "to_call": state.to_call, "opponents": state.opponents,
            "equity": round(eq, 3) if eq is not None else None,
            "required": equity.required_equity(state.pot, state.to_call),
            "baseline": base.action, "action": final.action, "amount": final.amount,
            "clamped": final.clamped, "strategy": self.profile.name,
            "reason": " ".join(coach), "response_time": round(time.time() - t0, 1),
        })

    def _context(self, state: TableState | None, sit: Situation | None) -> str:
        if state is None or sit is None:
            return f"[Tisch]\nNoch nichts erkannt.\n[Strategie]\n{self.profile.describe()}"
        lines = ["[Tisch]", self.tracker.summary()]
        if sit.equity is not None:
            required = equity.required_equity(sit.pot, sit.to_call)
            need = f", benötigt für den Call {round(required * 100)} %" if sit.to_call and required else ""
            lines += ["[Mathe]", f"Equity {round(sit.equity * 100)} % gegen {sit.opponents} "
                                 f"Zufallshand/-hände{need}. Stack {fmt_amount(sit.hero_stack)}."]
        lines += ["[Strategie]", self.profile.describe(sit)]
        return "\n".join(lines)

    def _decision_prompt(self, state: TableState, sit: Situation, base: Recommendation) -> str:
        allowed = (f"Raise erlaubt: {'ja' if self.profile.raise_allowed(sit) else 'nein'}. "
                   f"All-in erlaubt: {'ja' if self.profile.all_in_allowed(sit) else 'nein'}.")
        return (f"[ENTSCHEIDUNG]\n{self._context(state, sit)}\n"
                f"[Basis-Empfehlung der App]\n{base.action} {_amount(base)} ({base.note}). {allowed}")

    # --- conversation ---

    def _converse(self, text: str):
        self._talk_gen += 1
        gen = self._talk_gen
        self.speaker.stop()  # the player speaks: whatever was being said is cut off
        self._add_line("you", text)
        state = self.tracker.state
        sit = self._situation(state, self._model.get("equity")) if state else None
        reply: list[str] = []
        stream = MarkerStream()

        def handle(items):
            for kind, item in items:
                if kind == "marker":
                    self._apply_markers(parse_markers([item]))
                elif gen == self._talk_gen:
                    reply.append(item)
                    self.speaker.say(item)

        try:
            self.backend.ask(f"[FRAGE]\n{self._context(state, sit)}\n\nDer Spieler sagt: {text}", None,
                             on_delta=lambda d: handle(stream.feed(d)),
                             cancelled=lambda: gen != self._talk_gen)
            handle(stream.flush())
        except Exception as e:
            L.error(f"Gespräch fehlgeschlagen: {e}")
            reply.append("Ich erreiche Claude gerade nicht.")
        if reply:
            self._add_line("coach", " ".join(reply))

    def _apply_markers(self, parsed: dict):
        if parsed.get("strategy"):
            self.set_strategy(parsed["strategy"])
        if parsed.get("talkativeness") in ("still", "normal", "viel"):
            self.talkativeness = parsed["talkativeness"]
            self.cfg["talkativeness"] = self.talkativeness
            self._save_cfg(self.cfg)

    def _say(self, text: str):
        if self.talkativeness != "still" and not self._listening:
            self.speaker.say(text)

    # --- view model ---

    def _show_table(self, state: TableState, eq: float | None):
        self._update(
            hand=state.hero_cards, board=state.board, street=STREET_NAMES[state.street],
            position=state.hero_position, equity=eq,
            required=equity.required_equity(state.pot, state.to_call),
            pot=fmt_amount(state.pot) if state.pot is not None else None,
            to_call=fmt_amount(state.to_call) if state.to_call else None,
            opponents_n=state.opponents, opponents=self.tracker.opponents_view(),
        )

    def _add_line(self, who: str, text: str):
        self._transcript = (self._transcript + [{"who": who, "text": text}])[-TRANSCRIPT_LINES:]
        self._update()

    def _update(self, **changes):
        with self._lock:
            self._model.update(changes)
            self._model.update(
                transcript=self._transcript, muted=self.speaker.muted,
                strategy={"name": self.profile.name, **self.profile.to_dict()},
            )
            model = dict(self._model)
        self.view.render(model)

    # --- recording for replay ---

    def _record(self, img, reading):
        if not self.cfg.get("record"):
            return
        folder = os.path.join(SESSIONS_DIR, datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(folder, exist_ok=True)
        self._frame_no += 1
        stem = os.path.join(folder, f"{datetime.now().strftime('%H%M%S')}_{self._frame_no:04d}")
        img.save(stem + ".jpg", quality=85)
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(reading, f, ensure_ascii=False)


def _amount(rec: Recommendation) -> str:
    if rec.amount is None or rec.action in ("FOLD", "CHECK"):
        return ""
    return fmt_amount(rec.amount)


def _spoken(rec: Recommendation) -> str:
    """A sentence for the voice when the app itself has the last word."""
    words = {"FOLD": "Fold", "CHECK": "Check", "CALL": "Call", "RAISE": "Raise", "ALL-IN": "All-in"}
    head = f"{words.get(rec.action, rec.action)} {_amount(rec)}".strip()
    return f"{head}. {rec.note}." if rec.note else f"{head}."

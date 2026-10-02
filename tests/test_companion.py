import os
import tempfile
import time
import unittest
from unittest import mock

import history
from companion import Companion

READING = {
    "hero_cards": ["Kh", "Th"], "board": ["9h", "4c", "2h"], "pot": 160, "to_call": 40,
    "hero_stack": 1000, "hero_to_act": True, "buttons": ["Fold", "Call", "Raise"],
    "players": [{"name": "Tilly", "stack": 554, "in_hand": True, "last_action": "bet", "dealer": False}],
}


class FakeBackend:
    name = "fake"

    def __init__(self, answer, reading=READING):
        self.answer, self.reading, self.prompts, self.quick = answer, reading, [], []

    def read_table(self, img, quick=False):
        self.quick.append(quick)
        return self.reading

    def new_hand(self):
        pass

    def reset_conversation(self, seed=""):
        pass

    def ask(self, text, img=None, on_delta=None, cancelled=None):
        self.prompts.append(text)
        if isinstance(self.answer, Exception):
            raise self.answer
        for i in range(0, len(self.answer), 7):  # stream in small chunks
            on_delta(self.answer[i:i + 7])
        return self.answer

    def close(self):
        pass


class FakeView:
    def __init__(self):
        self.model = {}

    def render(self, model):
        self.model = model


class FakeSpeaker:
    muted = False

    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)

    def stop(self):
        pass

    def set_muted(self, muted):
        self.muted = muted


class CompanionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patcher = mock.patch.object(history, "HISTORY_FILE", os.path.join(self.tmp, "history.jsonl"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, answer, **cfg):
        self.backend, self.view, self.speaker = FakeBackend(answer), FakeView(), FakeSpeaker()
        base = {"crop_region": {"x": 0, "y": 0, "w": 10, "h": 10}, "strategy": {}, "window_guard": False}
        base.update(cfg)
        return Companion(base, self.backend, self.view, self.speaker)

    def advise(self, companion):
        with mock.patch("threading.Thread") as thread:  # run the advice inline
            thread.side_effect = lambda target, args=(), daemon=None: mock.Mock(
                start=lambda: target(*args))
            companion._read_and_apply(object(), "buttons", time.time())

    def test_advice_is_shown_but_not_spoken_unasked(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall, die Odds passen. Flush Draw mit Overcards.")
        self.advise(c)
        self.assertEqual(self.view.model["action"], "CALL")
        self.assertIn("Flush Draw", self.view.model["why"])
        self.assertEqual(self.speaker.said, [])

    def test_what_do_you_think_speaks_the_open_advice(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall, die Odds passen. Flush Draw mit Overcards.")
        self.advise(c)
        c.think_aloud()
        self.assertEqual(self.speaker.said, ["Call, die Odds passen.", "Flush Draw mit Overcards."])
        self.assertEqual(len(self.backend.prompts), 1)  # no second trip to the coach

    def test_what_do_you_think_speaks_the_capped_advice(self):
        c = self.make("[[EMPFEHLUNG RAISE 200]]\nRaise, mach Druck.")
        self.advise(c)
        c.think_aloud()
        self.assertEqual(len(self.speaker.said), 1)
        self.assertTrue(self.speaker.said[0].startswith("Call 40."))

    def test_what_do_you_think_without_a_decision_asks_the_coach(self):
        c = self.make("Gerade passiert nichts, wir warten auf Karten.")
        c.think_aloud()
        for _ in range(100):
            if self.speaker.said:
                break
            time.sleep(0.01)
        self.assertEqual(self.speaker.said, ["Gerade passiert nichts, wir warten auf Karten."])
        self.assertIn("[FRAGE]", self.backend.prompts[0])

    def test_panel_button_triggers_what_do_you_think(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.")
        self.advise(c)
        c.on_view_message({"type": "think"})
        self.assertEqual(self.speaker.said, ["Call."])

    def test_coach_within_guard_rails_is_spoken(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall, die Odds passen. Flush Draw mit Overcards.",
                      auto_speak=True)
        self.advise(c)
        m = self.view.model
        self.assertEqual((m["action"], m["amount"], m["source"]), ("CALL", "40", "Coach"))
        self.assertEqual(m["clamp_note"], "")
        self.assertEqual(self.speaker.said, ["Call, die Odds passen.", "Flush Draw mit Overcards."])
        self.assertIn("Flush Draw", m["why"])
        self.assertEqual(m["hand"], ["Kh", "Th"])
        self.assertAlmostEqual(m["required"], 0.2)

    def test_coach_raise_beyond_profile_is_capped(self):
        c = self.make("[[EMPFEHLUNG RAISE 200]]\nRaise, mach Druck.", auto_speak=True)
        self.advise(c)
        m = self.view.model
        self.assertEqual(m["action"], "CALL")
        self.assertEqual(m["clamp_note"], "begrenzt durch Strategie")
        self.assertNotIn("Raise, mach Druck.", self.speaker.said)
        self.assertTrue(self.speaker.said[0].startswith("Call 40."))

    def test_brain_failure_falls_back_to_baseline(self):
        c = self.make(RuntimeError("offline"), auto_speak=True)
        self.advise(c)
        m = self.view.model
        self.assertEqual(m["action"], "CALL")
        self.assertIn("Basis", m["source"])
        self.assertTrue(self.speaker.said[0].startswith("Call 40."))

    def test_prompt_carries_math_and_guard_rails(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.")
        self.advise(c)
        prompt = self.backend.prompts[0]
        for part in ("[ENTSCHEIDUNG]", "[Mathe]", "Equity", "benötigt für den Call 20 %",
                     "Moderat aggressiv", "Raise erlaubt: nein"):
            self.assertIn(part, prompt)

    def test_announcements_can_be_switched_on_by_voice(self):
        c = self.make("[[GESPRAECHIGKEIT normal]]\nMach ich.")
        c._converse("sag mir die Empfehlungen wieder an")
        self.assertTrue(c.auto_speak)
        self.assertTrue(c.cfg["auto_speak"])

    def test_decision_is_logged(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.")
        self.advise(c)
        with open(history.HISTORY_FILE) as f:
            line = f.read()
        self.assertIn('"action": "CALL"', line)
        self.assertIn('"baseline": "CALL"', line)

    def test_spoken_strategy_change_moves_the_dials(self):
        c = self.make("[[STRATEGIE aggression=1]]\nGut, ich nehme Tempo raus.")
        c._converse("spiel bitte vorsichtiger")
        self.assertEqual(c.profile.aggression, 1)
        self.assertEqual(self.speaker.said, ["Gut, ich nehme Tempo raus."])
        self.assertEqual(self.view.model["transcript"][0], {"who": "you", "text": "spiel bitte vorsichtiger"})

    def test_question_without_a_table_still_carries_the_strategy(self):
        c = self.make("Klar.")
        c._converse("spiel vorsichtiger")
        prompt = self.backend.prompts[0]
        self.assertIn("[FRAGE]", prompt)
        self.assertIn("Handauswahl 2/5", prompt)
        self.assertIn("Aggression 3/5", prompt)

    def test_talking_cuts_the_coach_off(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.", auto_speak=True)
        stopped = []
        self.speaker.stop = lambda: stopped.append(True)
        c.set_listening("listening")
        self.assertEqual(self.view.model["status"], "Höre zu")
        self.assertTrue(stopped)
        self.advise(c)
        self.assertEqual(self.speaker.said, [])  # nothing is spoken while the player talks
        self.assertEqual(self.view.model["action"], "CALL")
        c.set_listening("idle")
        c.think_aloud()
        self.assertEqual(self.speaker.said, ["Call."])

    def test_big_line_explains_the_move_in_plain_words(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.")
        self.advise(c)
        m = self.view.model
        self.assertEqual(m["gloss"], "Mitgehen: 40 zahlen")
        self.assertIn("Du bist dran. Mitgehen kostet 40.", m["events"])
        self.assertTrue(m["events"][-1].startswith("Neue Hand. Du hast K♥ T♥."))

    def test_waiting_shows_a_plan_for_the_next_move(self):
        c = self.make("unbenutzt")
        self.backend.reading = dict(READING, hero_to_act=False, to_call=0, buttons=[])
        self.advise(c)
        m = self.view.model
        self.assertIsNone(m["action"])
        self.assertEqual(m["wait_text"], "WARTEN")
        self.assertIn("Setzt jemand", m["plan"])
        self.assertEqual(self.backend.prompts, [])  # the plan is local math, no coach call

    def test_turn_reads_are_quick_and_table_reads_are_full(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.")
        self.advise(c)
        with mock.patch("threading.Thread"):
            c._read_and_apply(object(), "table", time.time())
        self.assertEqual(self.backend.quick, [True, False])

    def test_an_older_frame_never_overwrites_a_newer_reading(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.")
        self.advise(c)
        self.backend.reading = dict(READING, hero_cards=["2c", "3d"], board=[], hero_to_act=False)
        with mock.patch("threading.Thread"):
            c._read_and_apply(object(), "table", time.time() - 60)
        self.assertEqual(self.view.model["hand"], ["Kh", "Th"])

    def test_covered_table_is_not_read(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.", window_guard=True)
        c._window_pid = lambda: 111
        self.advise(c)                      # first valid reading: this window is the table
        c._window_pid = lambda: 222         # another app now covers the region
        reads = len(self.backend.quick)
        c._dispatch(object(), "buttons")
        time.sleep(0.2)
        self.assertEqual(len(self.backend.quick), reads)
        self.assertEqual(self.view.model["status"], "Tisch verdeckt, ich schaue nicht hin")

    def finish_hand(self, c, **next_hand):
        """Advise on the standard hand, then let the next hand begin."""
        self.advise(c)
        self.backend.answer = "Der Call war richtig, der Preis hat gepasst. Verloren hast du durch Pech."
        self.backend.reading = dict(READING, hero_cards=["Ah", "Kd"], board=[], pot=3, to_call=0,
                                    hero_to_act=False, buttons=[], **next_hand)
        self.advise(c)

    def test_debrief_after_each_hand(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall, der Preis passt.")
        self.finish_hand(c, hero_stack=960)
        prompt = self.backend.prompts[-1]
        self.assertTrue(prompt.startswith("[MANÖVERKRITIK]"))
        for part in ("Du hast K♥ T♥", "Empfehlung: CALL 40", "Du gehst mit.", "Du hast 40 verloren"):
            self.assertIn(part, prompt)
        m = self.view.model
        self.assertIn("Der Call war richtig", m["debrief"])
        self.assertIn("K♥ T♥", m["last_hand"])
        self.assertIn("40 verloren", m["last_hand"])
        with open(history.HISTORY_FILE, encoding="utf-8") as f:
            self.assertIn('"type": "hand"', f.read())

    def test_what_do_you_think_after_a_hand_speaks_the_debrief(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall, der Preis passt.")
        self.finish_hand(c, hero_stack=960)
        calls = len(self.backend.prompts)
        c.think_aloud()
        self.assertEqual(self.speaker.said, ["Der Call war richtig, der Preis hat gepasst.",
                                             "Verloren hast du durch Pech."])
        self.assertEqual(len(self.backend.prompts), calls)

    def test_questions_carry_the_last_hand_for_discussion(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall, der Preis passt.")
        self.finish_hand(c, hero_stack=1100)
        self.backend.answer = "Ja."
        c._converse("War mein Call richtig?")
        prompt = self.backend.prompts[-1]
        self.assertIn("[Letzte Hand]", prompt)
        self.assertIn("Empfehlung: CALL 40", prompt)
        self.assertIn("Du hast 100 gewonnen", prompt)

    def test_invalid_reading_is_not_advised(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.")
        self.backend.reading = dict(READING, board=["Kh", "4c", "2h"])  # Kh twice
        self.advise(c)
        self.assertEqual(self.view.model["status"], "Tisch nicht lesbar")
        self.assertEqual(self.backend.prompts, [])


if __name__ == "__main__":
    unittest.main()

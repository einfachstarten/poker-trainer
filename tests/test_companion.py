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
        self.answer, self.reading, self.prompts = answer, reading, []

    def read_table(self, img):
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
        base = {"crop_region": {"x": 0, "y": 0, "w": 10, "h": 10}, "strategy": {}}
        base.update(cfg)
        return Companion(base, self.backend, self.view, self.speaker)

    def advise(self, companion):
        with mock.patch("threading.Thread") as thread:  # run the advice inline
            thread.side_effect = lambda target, args=(), daemon=None: mock.Mock(
                start=lambda: target(*args))
            companion._on_frame(object(), "buttons")

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

    def test_invalid_reading_is_not_advised(self):
        c = self.make("[[EMPFEHLUNG CALL 40]]\nCall.")
        self.backend.reading = dict(READING, board=["Kh", "4c", "2h"])  # Kh twice
        self.advise(c)
        self.assertEqual(self.view.model["status"], "Tisch nicht lesbar")
        self.assertEqual(self.backend.prompts, [])


if __name__ == "__main__":
    unittest.main()

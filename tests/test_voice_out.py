import threading
import time
import unittest

import voice_out


class FakeEngine:
    """Speaks by sleeping; records what it was asked to say."""

    def __init__(self, seconds=0.05):
        self.seconds = seconds
        self.spoken = []
        self.stopped = 0
        self._cut = threading.Event()

    def speak(self, text):
        self._cut.clear()
        self.spoken.append(text)
        self._cut.wait(self.seconds)

    def stop(self):
        self.stopped += 1
        self._cut.set()


def wait_until(condition, seconds=2.0):
    end = time.time() + seconds
    while time.time() < end and not condition():
        time.sleep(0.01)


class SpeakerTest(unittest.TestCase):
    def test_sentences_are_spoken_in_order(self):
        engine = FakeEngine()
        speaker = voice_out.Speaker(engine=engine)
        speaker.say("Eins.")
        speaker.say("Zwei.")
        wait_until(lambda: len(engine.spoken) == 2)
        self.assertEqual(engine.spoken, ["Eins.", "Zwei."])

    def test_stop_cuts_the_current_sentence_and_drops_the_queue(self):
        engine = FakeEngine(seconds=1.0)
        speaker = voice_out.Speaker(engine=engine)
        for text in ("Eins.", "Zwei.", "Drei."):
            speaker.say(text)
        wait_until(lambda: engine.spoken == ["Eins."])
        speaker.stop()
        time.sleep(0.2)
        self.assertEqual(engine.spoken, ["Eins."])
        self.assertGreaterEqual(engine.stopped, 1)
        speaker.say("Vier.")
        wait_until(lambda: len(engine.spoken) == 2)
        self.assertEqual(engine.spoken, ["Eins.", "Vier."])

    def test_text_is_made_speakable_with_the_engines_pronunciation(self):
        engine = FakeEngine()
        engine.pronunciation = {"Raise": "Räis"}
        speaker = voice_out.Speaker(engine=engine)
        speaker.say("K♥ → Raise 54 %")
        wait_until(lambda: engine.spoken)
        self.assertEqual(engine.spoken, ["K Herz Räis 54 Prozent"])

    def test_engine_without_pronunciation_table_gets_plain_text(self):
        engine = FakeEngine()
        speaker = voice_out.Speaker(engine=engine)
        speaker.say("Raise auf 60.")
        wait_until(lambda: engine.spoken)
        self.assertEqual(engine.spoken, ["Raise auf 60."])

    def test_a_failing_engine_does_not_kill_the_speaker(self):
        engine = FakeEngine()
        calls = []

        def boom(text):
            calls.append(text)
            if len(calls) == 1:
                raise RuntimeError("kaputt")

        engine.speak = boom
        speaker = voice_out.Speaker(engine=engine)
        speaker.say("Eins.")
        speaker.say("Zwei.")
        wait_until(lambda: len(calls) == 2)
        self.assertEqual(calls, ["Eins.", "Zwei."])


if __name__ == "__main__":
    unittest.main()

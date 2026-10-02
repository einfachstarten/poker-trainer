import threading
import time
import unittest
import unittest.mock

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



class FakeSoundDevice:
    def __init__(self):
        self.played, self.stops = [], 0

    def play(self, samples, rate):
        self.played.append((list(samples), rate))

    def wait(self):
        pass

    def stop(self):
        self.stops += 1


class SampleEngineTest(unittest.TestCase):
    def setUp(self):
        import sys
        self.sd = FakeSoundDevice()
        self._old = sys.modules.get("sounddevice")
        sys.modules["sounddevice"] = self.sd
        self.addCleanup(lambda: sys.modules.__setitem__("sounddevice", self._old)
                        if self._old else sys.modules.pop("sounddevice"))

    def test_speak_synthesizes_and_plays(self):
        engine = voice_out.SampleEngine(lambda text: ([0.1, 0.2], 44100))
        engine.speak("Hallo.")
        self.assertEqual(self.sd.played, [([0.1, 0.2], 44100)])

    def test_prepared_sentences_are_synthesized_ahead_and_only_once(self):
        calls = []

        def synth(text):
            calls.append(text)
            return [len(calls)], 24000

        engine = voice_out.SampleEngine(synth)
        engine.prepare("Eins.")
        engine.prepare("Zwei.")
        wait_until(lambda: len(calls) == 2)   # both are ready before anything is played
        self.assertEqual(self.sd.played, [])
        engine.speak("Eins.")
        engine.speak("Zwei.")
        self.assertEqual(calls, ["Eins.", "Zwei."])
        self.assertEqual([p[0] for p in self.sd.played], [[1], [2]])

    def test_stop_forgets_prepared_sentences(self):
        calls = []
        engine = voice_out.SampleEngine(lambda text: (calls.append(text) or [0.0], 24000))
        engine.prepare("Alt.")
        wait_until(lambda: calls == ["Alt."])
        engine.stop()
        engine.speak("Alt.")
        self.assertEqual(calls, ["Alt.", "Alt."])  # synthesized again, the old result was dropped
        self.assertEqual(self.sd.stops, 1)

    def test_speaker_hands_sentences_to_the_engine_early(self):
        prepared = []
        engine = FakeEngine()
        engine.prepare = prepared.append
        speaker = voice_out.Speaker(engine=engine)
        speaker.say("Eins.")
        speaker.say("Zwei.")
        self.assertEqual(prepared, ["Eins.", "Zwei."])


class MakeEngineTest(unittest.TestCase):
    def test_say_when_asked_for(self):
        engine = voice_out.make_engine({"voice_engine": "say", "voice": "Anna"})
        self.assertIsInstance(engine, voice_out.SayEngine)
        self.assertEqual(engine.voice, "Anna")

    def test_falls_back_to_say_without_the_neural_package(self):
        with unittest.mock.patch.object(voice_out, "supertonic_available", lambda: False):
            engine = voice_out.make_engine({"voice_engine": "auto", "voice": "M5"})
        self.assertIsInstance(engine, voice_out.SayEngine)

    def test_neural_voice_when_available(self):
        with unittest.mock.patch.object(voice_out, "supertonic_available", lambda: True), \
                unittest.mock.patch.object(voice_out, "SupertonicVoice") as voice:
            engine = voice_out.make_engine({"voice_engine": "auto", "voice": None})
        self.assertIsInstance(engine, voice_out.SampleEngine)
        voice.assert_called_once_with("M5")


if __name__ == "__main__":
    unittest.main()

import time
import unittest

import numpy as np

import voice_in


class FakeStream:
    """Stands in for the microphone: delivers the given samples in blocks while 'recording'."""

    def __init__(self, samples):
        self.samples = samples
        self.started = self.closed = False

    def start(self, on_block):
        self.started = True
        for i in range(0, len(self.samples), 1600):
            on_block(self.samples[i:i + 1600])

    def close(self):
        self.closed = True


def speech(seconds, level=0.1):
    return (np.random.RandomState(1).rand(int(16000 * seconds)).astype(np.float32) - 0.5) * 2 * level


class ListenerTest(unittest.TestCase):
    def make(self, samples, text="Soll ich callen?"):
        self.heard, self.states, self.audio = [], [], []
        self.stream = FakeStream(samples)

        def transcribe(audio):
            self.audio.append(audio)
            return text

        return voice_in.Listener(on_text=self.heard.append, on_state=self.states.append,
                                 transcribe=transcribe, open_stream=lambda: self.stream)

    def wait(self):
        for _ in range(100):
            if self.states and self.states[-1] == "idle":
                return
            time.sleep(0.01)

    def test_press_and_release_delivers_text(self):
        listener = self.make(speech(1.5))
        listener.press()
        listener.release()
        self.wait()
        self.assertEqual(self.heard, ["Soll ich callen?"])
        self.assertEqual(self.states, ["listening", "transcribing", "idle"])
        self.assertEqual(len(self.audio[0]), 24000)
        self.assertTrue(self.stream.closed)

    def test_short_tap_is_ignored(self):
        listener = self.make(speech(0.1))
        listener.press()
        listener.release()
        self.wait()
        self.assertEqual(self.heard, [])
        self.assertEqual(self.audio, [])

    def test_silence_is_not_sent_to_whisper(self):
        listener = self.make(np.zeros(32000, dtype=np.float32))
        listener.press()
        listener.release()
        self.wait()
        self.assertEqual(self.heard, [])
        self.assertEqual(self.audio, [])

    def test_empty_transcript_is_dropped(self):
        listener = self.make(speech(1.0), text="  ")
        listener.press()
        listener.release()
        self.wait()
        self.assertEqual(self.heard, [])

    def test_key_repeat_does_not_restart(self):
        listener = self.make(speech(1.0))
        listener.press()
        listener.press()
        listener.release()
        listener.release()
        self.wait()
        self.assertEqual(self.heard, ["Soll ich callen?"])


if __name__ == "__main__":
    unittest.main()

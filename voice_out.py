"""Speech output: a sentence queue in front of an exchangeable voice engine.

An engine needs speak(text), which blocks until the sentence has been spoken, and stop(),
which cuts it off from another thread. Optional: a `pronunciation` dict for words the
voice gets wrong.
"""

from __future__ import annotations

import queue
import subprocess
import threading

import log
from speech_text import speakable

L = log.get("voice")

# The German system voice reads some English poker terms with German phonetics ("Raise"
# comes out as "Reise"). This table respells the ones that came out wrong in a say → Whisper
# round trip with the voice Anna. Call, Fold, Check, River, Equity, All-in were fine as written.
SAY_PRONUNCIATION = {
    "Raise": "Räis",
    "Raises": "Räises",
    "raisen": "räisen",
    "Button": "Batten",
    "Turn": "Törn",
}


def german_voices() -> list[str]:
    """Installed German `say` voices, best quality first."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for line in out.splitlines():
        if " de_DE " not in line:
            continue
        name = line.split(" de_DE ")[0].strip()
        if name not in names:
            names.append(name)

    def rank(name: str) -> int:
        if "Premium" in name:
            return 0
        if "Enhanced" in name or "Erweitert" in name:
            return 1
        return 2 if name.startswith("Anna") else 3

    return sorted(names, key=rank)


class SayEngine:
    """The macOS system voice. Always available, but it sounds synthetic."""

    pronunciation = SAY_PRONUNCIATION

    def __init__(self, voice: str | None = None, rate: int = 190):
        self.voice = voice or (german_voices() or ["Anna"])[0]
        self.rate = rate
        self._proc: subprocess.Popen | None = None

    def speak(self, text: str):
        self._proc = subprocess.Popen(["say", "-v", self.voice, "-r", str(self.rate), text])
        self._proc.wait()

    def stop(self):
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()


class SampleEngine:
    """A neural voice: synthesize(text) → (float32 samples, sample rate), played through sounddevice."""

    def __init__(self, synthesize, pronunciation: dict | None = None):
        self._synthesize = synthesize
        self.pronunciation = pronunciation or {}

    def speak(self, text: str):
        import sounddevice
        samples, rate = self._synthesize(text)
        sounddevice.play(samples, rate)
        sounddevice.wait()

    def stop(self):
        import sounddevice
        sounddevice.stop()


class Speaker:
    def __init__(self, engine=None):
        self.engine = engine or SayEngine()
        self._queue: queue.Queue = queue.Queue()
        self._generation = 0
        self._speaking = False
        threading.Thread(target=self._run, daemon=True).start()
        L.info(f"Sprachausgabe: {type(self.engine).__name__}")

    def say(self, text: str):
        text = speakable(text, getattr(self.engine, "pronunciation", None) or {})
        if text:
            self._queue.put((self._generation, text))

    def stop(self):
        """Drop everything queued and cut off the sentence being spoken."""
        self._generation += 1
        if self._speaking:
            self.engine.stop()

    @property
    def speaking(self) -> bool:
        return self._speaking or not self._queue.empty()

    def _run(self):
        while True:
            generation, text = self._queue.get()
            if generation != self._generation:
                continue
            self._speaking = True
            try:
                self.engine.speak(text)
            except Exception as e:
                L.warning(f"Sprachausgabe fehlgeschlagen: {e}")
            finally:
                self._speaking = False

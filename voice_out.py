"""Speech output: a sentence queue in front of an exchangeable voice engine.

An engine needs speak(text), which blocks until the sentence has been spoken, and stop(),
which cuts it off from another thread. Optional: a `pronunciation` dict for words the
voice gets wrong.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

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
    """A neural voice: synthesize(text) → (float32 samples, sample rate), played through sounddevice.

    Synthesis takes a second or two per sentence. prepare() starts it as soon as a sentence is
    known, so the next one is ready when the current one has been spoken.
    """

    def __init__(self, synthesize, pronunciation: dict | None = None):
        self._synthesize = synthesize
        self.pronunciation = pronunciation or {}
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._ready: dict = {}

    def prepare(self, text: str):
        if text not in self._ready:
            self._ready[text] = self._pool.submit(self._synthesize, text)

    def speak(self, text: str):
        import sounddevice
        self.prepare(text)
        samples, rate = self._ready.pop(text).result()
        sounddevice.play(samples, rate)
        sounddevice.wait()

    def stop(self):
        import sounddevice
        for job in self._ready.values():
            job.cancel()
        self._ready = {}
        sounddevice.stop()


MODEL_DIR = os.path.expanduser("~/.poker-trainer/models/supertonic3")
SUPERTONIC_VOICES = ("F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5")
DEFAULT_SUPERTONIC_VOICE = "M5"


def supertonic_available() -> bool:
    try:
        import sounddevice  # noqa: F401
        import supertonic  # noqa: F401
        return True
    except ImportError:
        return False


class SupertonicVoice:
    """Supertonic 3, a local neural voice. The model (about 400 MB) is fetched on first use."""

    def __init__(self, voice: str = DEFAULT_SUPERTONIC_VOICE):
        self.voice = voice
        self._tts = None
        self._style = None
        self._lock = threading.Lock()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        with self._lock:
            if self._tts is not None:
                return
            import numpy as np
            from supertonic import TTS
            self._np = np
            self._tts = TTS(model="supertonic-3", model_dir=MODEL_DIR, auto_download=True)
            self._style = self._tts.get_voice_style(self.voice)
            self._tts.synthesize("Bereit.", voice_style=self._style, lang="de")  # first run is slow
            L.info(f"Stimme Supertonic {self.voice} geladen")

    def __call__(self, text: str):
        self._load()
        wav, _ = self._tts.synthesize(text, voice_style=self._style, lang="de")
        return self._np.asarray(wav, dtype=self._np.float32).reshape(-1), self._tts.sample_rate


def make_engine(cfg: dict):
    """The voice from the config: 'supertonic', 'say', or 'auto' (neural if installed)."""
    choice = cfg.get("voice_engine", "auto")
    voice = cfg.get("voice")
    if choice in ("auto", "supertonic") and supertonic_available():
        return SampleEngine(SupertonicVoice(voice if voice in SUPERTONIC_VOICES else DEFAULT_SUPERTONIC_VOICE))
    return SayEngine(voice if voice not in SUPERTONIC_VOICES else None)


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
            if hasattr(self.engine, "prepare"):
                self.engine.prepare(text)
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

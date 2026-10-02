"""Speech input: hold a key, talk, let go. Recording and transcription stay on this Mac."""

from __future__ import annotations

import threading

import numpy as np

import log

L = log.get("listen")

SAMPLE_RATE = 16000
MIN_SECONDS = 0.4
MIN_RMS = 0.004  # below this the recording is silence, which Whisper likes to fill with invented text
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
VOCABULARY = ("Poker-Gespräch auf Deutsch mit englischen Fachbegriffen: Call, Raise, Fold, Check, All-in, "
              "Flop, Turn, River, Button, Big Blind, Pot Odds, Equity, Flush Draw, Straight, Bluff, Shove, "
              "suited, Continuation Bet.")


def available() -> bool:
    """True if the packages for local speech input are installed."""
    try:
        import mlx_whisper  # noqa: F401
        import sounddevice  # noqa: F401
        return True
    except ImportError:
        return False


class _Microphone:
    def __init__(self):
        self._stream = None

    def start(self, on_block):
        import sounddevice
        self._stream = sounddevice.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            callback=lambda data, frames, time, status: on_block(data[:, 0].copy()))
        self._stream.start()

    def close(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def whisper_transcribe(audio: np.ndarray) -> str:
    import mlx_whisper
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=WHISPER_MODEL, language="de",
                                    initial_prompt=VOCABULARY, condition_on_previous_text=False)
    return result["text"]


def warm_up():
    """Load the model ahead of the first question. The very first run downloads about 1.5 GB."""
    try:
        whisper_transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
        L.info("Sprachmodell geladen")
    except Exception as e:
        L.warning(f"Sprachmodell nicht geladen: {e}")


class Listener:
    """Push-to-talk. press() starts recording, release() transcribes and calls on_text(text)."""

    def __init__(self, on_text, on_state=None, transcribe=whisper_transcribe, open_stream=_Microphone):
        self._on_text = on_text
        self._on_state = on_state or (lambda state: None)
        self._transcribe = transcribe
        self._open_stream = open_stream
        self._stream = None
        self._blocks: list[np.ndarray] = []
        self._lock = threading.Lock()

    def press(self):
        with self._lock:
            if self._stream is not None:
                return  # key repeat
            self._blocks = []
            self._stream = self._open_stream()
        self._on_state("listening")
        try:
            self._stream.start(self._blocks.append)
        except Exception as e:
            L.error(f"Mikrofon nicht verfügbar: {e}")
            self._stream = None
            self._on_state("idle")

    def release(self):
        with self._lock:
            stream, self._stream = self._stream, None
        if stream is None:
            return
        stream.close()
        audio = np.concatenate(self._blocks) if self._blocks else np.zeros(0, dtype=np.float32)
        threading.Thread(target=self._finish, args=(audio,), daemon=True).start()

    def _finish(self, audio: np.ndarray):
        try:
            if len(audio) < MIN_SECONDS * SAMPLE_RATE or float(np.sqrt(np.mean(audio ** 2))) < MIN_RMS:
                return
            self._on_state("transcribing")
            text = self._transcribe(audio).strip()
            L.info(f"Gehört ({len(audio) / SAMPLE_RATE:.1f}s): {text}")
            if text:
                self._on_text(text)
        except Exception as e:
            L.error(f"Transkription fehlgeschlagen: {e}")
        finally:
            self._on_state("idle")

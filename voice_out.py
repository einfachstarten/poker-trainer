"""Speech output: a sentence queue on top of macOS `say`, interruptible at any time."""

from __future__ import annotations

import queue
import subprocess
import threading

import log
from speech_text import speakable

L = log.get("voice")

# A German voice reads some English poker terms with German phonetics ("Raise" comes out
# as "Reise"). This table respells the ones that came out wrong in a say → Whisper round
# trip with the voice Anna. Call, Fold, Check, River, Equity, All-in were fine as written.
PRONUNCIATION = {
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


class Speaker:
    def __init__(self, voice: str | None = None, rate: int = 190, pronunciation: dict | None = None):
        self.voice = voice or (german_voices() or ["Anna"])[0]
        self.rate = rate
        self.muted = False
        self._pronunciation = {**PRONUNCIATION, **(pronunciation or {})}
        self._queue: queue.Queue = queue.Queue()
        self._current: subprocess.Popen | None = None
        self._generation = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()
        L.info(f"Sprachausgabe: Stimme {self.voice}, {rate} Wörter/min")

    def say(self, text: str):
        if self.muted or not text.strip():
            return
        self._queue.put((self._generation, speakable(text, self._pronunciation)))

    def stop(self):
        """Drop everything queued and cut off the sentence being spoken."""
        with self._lock:
            self._generation += 1
            current = self._current
        if current and current.poll() is None:
            current.terminate()

    def set_muted(self, muted: bool):
        self.muted = muted
        if muted:
            self.stop()

    @property
    def speaking(self) -> bool:
        current = self._current
        return bool(current and current.poll() is None) or not self._queue.empty()

    def _run(self):
        while True:
            generation, text = self._queue.get()
            with self._lock:
                if generation != self._generation or not text:
                    continue
                try:
                    self._current = subprocess.Popen(["say", "-v", self.voice, "-r", str(self.rate), text])
                except OSError as e:
                    L.warning(f"say fehlgeschlagen: {e}")
                    continue
            self._current.wait()

"""Text plumbing between the LLM stream, the panel and the speech output.

The LLM answers in plain sentences and may add control lines like [[EMPFEHLUNG CALL 40]].
Those markers are parsed by the app and never shown or spoken.
"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*(?=\s)|\n+")
_SUIT_WORDS = {"♠": " Pik", "♥": " Herz", "♦": " Karo", "♣": " Kreuz"}
_AMOUNT = re.compile(r"-?\d+(?:[.,]\d+)?")


class MarkerStream:
    """Feed text deltas, get complete ('sentence', text) and ('marker', text) items back."""

    def __init__(self):
        self._buf = ""

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self._buf += chunk
        out = []
        while True:
            self._buf = self._buf.lstrip()
            if self._buf.startswith("[["):
                end = self._buf.find("]]")
                if end < 0:
                    break
                out.append(("marker", self._buf[2:end].strip()))
                self._buf = self._buf[end + 2:]
                continue
            marker_at = self._buf.find("[[")
            text = self._buf if marker_at < 0 else self._buf[:marker_at]
            match = _SENTENCE_END.search(text)
            if match:
                sentence = text[:match.end()].strip()
                if sentence:
                    out.append(("sentence", sentence))
                self._buf = self._buf[match.end():]
                continue
            if marker_at > 0:
                # a marker starts mid-text: whatever stands before it is a finished sentence
                if text.strip():
                    out.append(("sentence", text.strip()))
                self._buf = self._buf[marker_at:]
                continue
            break
        return out

    def flush(self) -> list[tuple[str, str]]:
        rest, self._buf = self._buf.strip(), ""
        if not rest or rest.startswith("[["):
            return []
        return [("sentence", rest)]


def parse_markers(markers: list[str]) -> dict:
    """['EMPFEHLUNG RAISE 60', 'STRATEGIE aggression=2'] → structured dict. Unknown markers are ignored."""
    result: dict = {}
    for marker in markers:
        parts = marker.split()
        if not parts:
            continue
        kind, args = parts[0].upper(), parts[1:]
        if kind == "EMPFEHLUNG" and args:
            amount = None
            if len(args) > 1:
                found = _AMOUNT.search(args[1])
                amount = float(found.group().replace(",", ".")) if found else None
            result["recommendation"] = (args[0].upper(), amount)
        elif kind == "STRATEGIE":
            changes = {}
            for arg in args:
                key, _, value = arg.partition("=")
                if key in ("tightness", "aggression", "bluff") and value.isdigit():
                    changes[key] = int(value)
            if changes:
                result["strategy"] = changes
        elif kind == "GESPRAECHIGKEIT" and args:
            result["talkativeness"] = args[0].lower()
        elif kind == "KARTEN" and args:
            result["cards"] = args
    return result


def speakable(text: str, pronunciation: dict[str, str]) -> str:
    """Make a sentence fit for the speech synthesizer: no symbols, German-friendly spelling."""
    for symbol, word in _SUIT_WORDS.items():
        text = text.replace(symbol, word)
    text = text.replace("→", " ").replace("—", ", ").replace("–", ", ")
    text = re.sub(r"\s*%", " Prozent", text)
    text = re.sub(r"[*#`_]", "", text)
    for word, spoken in pronunciation.items():
        text = re.sub(rf"\b{re.escape(word)}\b", spoken, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()

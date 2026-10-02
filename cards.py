"""Card notation: normalize whatever the vision model returns to 'Th', 'Ks', ..."""

from __future__ import annotations

import re

RANKS = "23456789TJQKA"
SUITS = "shdc"
SUIT_SYMBOLS = {"♠": "s", "♥": "h", "♦": "d", "♣": "c", "♤": "s", "♡": "h", "♢": "d", "♧": "c"}
PRETTY_SUITS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

_CARD_RE = re.compile(r"^(10|[2-9TJQKA])([SHDC])$")
_SPLIT_RE = re.compile(r"[\s,;|]+")


def normalize_card(raw) -> str | None:
    """'T♥', '10h', 'th' → 'Th'. Returns None for anything that is not a card."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    for symbol, letter in SUIT_SYMBOLS.items():
        text = text.replace(symbol, letter)
    text = re.sub(r"\s+", "", text).upper()
    match = _CARD_RE.match(text)
    if not match:
        return None
    rank = "T" if match.group(1) == "10" else match.group(1)
    return rank + match.group(2).lower()


def normalize_cards(raw) -> list[str]:
    """Accepts a list or a string like 'T♥ K♥'. Unreadable entries are dropped."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [p for p in _SPLIT_RE.split(raw.strip()) if p]
    result = []
    for item in raw:
        card = normalize_card(item)
        if card:
            result.append(card)
    return result


def valid_deal(hero: list[str], board: list[str]) -> bool:
    """Two hole cards, 0/3/4/5 board cards, no card twice."""
    if len(hero) != 2 or len(board) not in (0, 3, 4, 5):
        return False
    everything = hero + board
    if any(normalize_card(c) != c for c in everything):
        return False
    return len(set(everything)) == len(everything)


def hand_class(hero: list[str]) -> str | None:
    """['Kh', 'Ah'] → 'AKs', pairs → 'TT', offsuit → 'AKo'."""
    if len(hero) != 2:
        return None
    a, b = sorted(hero, key=lambda c: RANKS.index(c[0]), reverse=True)
    if a[0] == b[0]:
        return a[0] + b[0]
    return a[0] + b[0] + ("s" if a[1] == b[1] else "o")


def pretty(card: str) -> str:
    return card[0] + PRETTY_SUITS.get(card[1], card[1])


def pretty_list(cards: list[str]) -> str:
    return " ".join(pretty(c) for c in cards)

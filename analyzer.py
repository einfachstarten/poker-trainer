"""Claude Vision API poker analysis — quick + detail mode."""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass

from PIL import Image
import log

L = log.get("analyzer")

PLAY_STYLES = {
    "TAG": {
        "name": "Tight-Aggressive",
        "desc": "Wenige Hände, aber aggressiv spielen. Nur Premium-Hände und starke Draws.",
        "prompt": "SPIELSTIL: Tight-Aggressive (TAG). Spiele nur starke Hände (Top 15-20%), aber spiele sie aggressiv. Folde schwache Hände konsequent. Raise statt Call bevorzugen. Position ist sehr wichtig.",
    },
    "LAG": {
        "name": "Loose-Aggressive",
        "desc": "Viele Hände, aggressiv spielen. Druck auf Gegner ausüben, viele Bluffs.",
        "prompt": "SPIELSTIL: Loose-Aggressive (LAG). Spiele ein breites Spektrum an Händen aggressiv. Nutze Position und Initiative. Bluffing und Semi-Bluffs sind wichtige Waffen. Setze Gegner unter Druck.",
    },
    "Conservative": {
        "name": "Konservativ",
        "desc": "Sehr sicher spielen. Nur die besten Hände, kaum Risiko.",
        "prompt": "SPIELSTIL: Konservativ/Tight-Passive. Spiele nur Premium-Hände (Top 10%). Vermeide Risiko. Calle eher als zu raisen. Im Zweifel folden. Bankroll-Schutz hat Priorität.",
    },
    "Balanced": {
        "name": "Balanced",
        "desc": "Ausgewogener GTO-Stil. Mix aus Aggression und Vorsicht.",
        "prompt": "SPIELSTIL: Balanced/GTO-orientiert. Spiele einen ausgewogenen Mix. Variiere zwischen Raise und Call. Nutze Position, aber nicht überaggressiv. Solides ABC-Poker mit gelegentlichen Bluffs.",
    },
}

DEFAULT_STYLE = "TAG"

QUICK_PROMPT_TEMPLATE = """Poker-Coach. Screenshot analysieren.

SPIELER: Sitzt UNTEN am Tisch, wo Aktionsbuttons sind (Fold/Check/Call/Raise). Seine Hole Cards sind dort.
Wenn Aktionsbuttons sichtbar → Spieler ist dran und HAT Karten.
Wenn KEINE Buttons/Karten → ACTION: WAIT

{style_prompt}

KRITISCH: Deine KOMPLETTE Antwort besteht aus GENAU 5 Zeilen. Kein Text davor. Kein Text danach. Keine Erklärung. Keine Analyse. Nur diese 5 Zeilen:

ACTION: FOLD|CHECK|CALL|RAISE|ALL-IN|WAIT
AMOUNT: Betrag oder -
HAND: deine Karten
POTODDS: z.B. 3:1 oder -
EQUITY: z.B. 65% oder -"""

DETAIL_PROMPT_TEMPLATE = """Du bist ein Poker-Coach. Quick-Analyse dieses Tisches:

{quick_result}

Der gecoachte Spieler sitzt unten am Tisch (dort wo die Aktionsbuttons sind).

{style_prompt}

AUSGABE — NUR diese 3 Zeilen, NICHTS anderes:
REASON: 2-3 Sätze strategische Begründung inkl. Pot Odds und Equity
BOARD: Community Cards oder -
OPPONENTS: Gegner-Aktionen z.B. "UTG raised 3x, BTN called" oder -"""

MAX_IMAGE_WIDTH = 800
MAX_OPPONENT_HISTORY = 20


@dataclass
class PokerTip:
    action: str
    amount: str
    reason: str
    hand: str
    board: str
    raw: str
    pot_odds: str = "-"
    equity: str = "-"
    opponents: str = "-"

    @property
    def color(self) -> str:
        if self.action in ("RAISE", "ALL-IN"):
            return "#00CC00"
        if self.action in ("CALL", "CHECK"):
            return "#FFAA00"
        if self.action == "WAIT":
            return "#666666"
        return "#FF4444"

    @property
    def is_actionable(self) -> bool:
        return self.action not in ("WAIT", "?")


def parse_response(text: str) -> PokerTip:
    fields = {}
    for line in text.strip().splitlines():
        match = re.match(r"^(ACTION|AMOUNT|REASON|HAND|BOARD|POTODDS|EQUITY|OPPONENTS):\s*(.+)", line.strip())
        if match:
            fields[match.group(1)] = match.group(2).strip()

    tip = PokerTip(
        action=fields.get("ACTION", "?"),
        amount=fields.get("AMOUNT", "-"),
        reason=fields.get("REASON", ""),
        hand=fields.get("HAND", "?"),
        board=fields.get("BOARD", "-"),
        raw=text,
        pot_odds=fields.get("POTODDS", "-"),
        equity=fields.get("EQUITY", "-"),
        opponents=fields.get("OPPONENTS", "-"),
    )
    L.debug(f"Parsed: {tip.action} {tip.amount} odds={tip.pot_odds} eq={tip.equity}")
    return tip


def optimize_image(img: Image.Image) -> str:
    """Resize + JPEG encode for fast API transfer."""
    w, h = img.size
    if w > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / w
        img = img.resize((MAX_IMAGE_WIDTH, int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    L.debug(f"Image optimized: {w}x{h} → {img.size[0]}x{img.size[1]}, {len(b64)} chars")
    return b64


class Analyzer:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", style: str = DEFAULT_STYLE):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.style = style
        self._opponent_history: list[str] = []
        self._last_b64: str | None = None
        self._last_quick_tip: PokerTip | None = None
        L.info(f"Analyzer bereit: model={model}, style={style}, key=...{api_key[-8:]}")

    def set_style(self, style: str):
        if style in PLAY_STYLES:
            self.style = style
            L.info(f"Spielstil geändert: {PLAY_STYLES[style]['name']}")

    def _get_style_prompt(self) -> str:
        return PLAY_STYLES.get(self.style, PLAY_STYLES[DEFAULT_STYLE])["prompt"]

    def _build_opponent_context(self) -> str:
        if not self._opponent_history:
            return ""
        lines = "\n".join(f"  - {entry}" for entry in self._opponent_history[-MAX_OPPONENT_HISTORY:])
        return f"\n\nGegner-Beobachtungen aus vorherigen Händen:\n{lines}\nNutze diese Info um Gegner-Tendenzen einzuschätzen (tight/loose, aggressive/passive)."

    def _track_opponents(self, tip: PokerTip):
        if tip.opponents and tip.opponents != "-":
            self._opponent_history.append(tip.opponents)
            L.debug(f"Opponent tracking: {len(self._opponent_history)} entries")

    def analyze_quick(self, img: Image.Image, on_action=None) -> PokerTip | None:
        """Fast analysis: ACTION, AMOUNT, HAND, POTODDS, EQUITY only."""
        b64 = optimize_image(img)
        self._last_b64 = b64
        self._last_quick_tip = None

        opponent_ctx = self._build_opponent_context()
        user_text = "Analysiere diesen Poker-Tisch."
        if opponent_ctx:
            user_text += opponent_ctx

        try:
            L.info(f"Quick API Request ({len(self._opponent_history)} opponent entries)...")
            collected = ""
            action_sent = False
            with self.client.messages.stream(
                model=self.model,
                max_tokens=120,
                system=QUICK_PROMPT_TEMPLATE.format(style_prompt=self._get_style_prompt()),
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": user_text,
                        },
                    ],
                }],
            ) as stream:
                for text in stream.text_stream:
                    collected += text
                    if on_action and not action_sent and "ACTION:" in collected:
                        match = re.search(r"ACTION:\s*(\S+)", collected)
                        if match:
                            action_sent = True
                            on_action(match.group(1))

            L.info(f"Quick Response: {collected.strip()}")
            tip = parse_response(collected)
            self._last_quick_tip = tip
            return tip
        except Exception as e:
            L.error(f"Quick Stream Error: {e}")
            return None

    def analyze_detail(self) -> PokerTip | None:
        """Detail analysis: REASON, BOARD, OPPONENTS. Uses last screenshot."""
        if not self._last_b64 or not self._last_quick_tip:
            L.warning("No quick analysis to detail — press F1 first")
            return None

        quick = self._last_quick_tip
        quick_summary = f"ACTION: {quick.action}\nAMOUNT: {quick.amount}\nHAND: {quick.hand}\nPOTODDS: {quick.pot_odds}\nEQUITY: {quick.equity}"

        try:
            L.info("Detail API Request...")
            collected = ""
            with self.client.messages.stream(
                model=self.model,
                max_tokens=250,
                system=DETAIL_PROMPT_TEMPLATE.format(
                    quick_result=quick_summary,
                    style_prompt=self._get_style_prompt(),
                ),
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": self._last_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Gib mir die ausführliche Analyse.",
                        },
                    ],
                }],
            ) as stream:
                for text in stream.text_stream:
                    collected += text

            L.info(f"Detail Response: {collected.strip()}")
            detail = parse_response(collected)

            # Merge detail into quick tip
            quick.reason = detail.reason
            quick.board = detail.board
            quick.opponents = detail.opponents
            quick.raw += "\n" + collected

            self._track_opponents(quick)
            return quick
        except Exception as e:
            L.error(f"Detail Stream Error: {e}")
            return None

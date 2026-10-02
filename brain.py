"""Access to Claude: `claude -p` headless with the user's subscription, API key as fallback.

Two roles share one backend:
- eyes:  read_table(img) → dict, reads the table and nothing else
- voice: ask(text, ...) → str, the conversation with the player
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import threading

from PIL import Image

import log

L = log.get("brain")

CLAUDE_LOG = "/tmp/poker-trainer-claude.log"
CLAUDE_CANDIDATES = ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")

EYES_SYSTEM = """Du liest einen Texas-Hold'em-Tisch aus einem Screenshot aus. Du gibst keine Empfehlung.
Antworte NUR mit einem JSON-Objekt, ohne Markdown, ohne Erklärung:
{"hero_cards": ["5c","6s"], "board": ["7s","Qh","7c"], "pot": 10, "to_call": 0, "hero_stack": 2762,
 "hero_to_act": true, "buttons": ["Fold","Check","Raise"], "hero_dealer": false, "big_blind": 2,
 "facing_raise": false,
 "players": [{"name": "Tilly", "stack": 554, "in_hand": true, "last_action": "check", "dealer": false}]}
Regeln:
- Hero sitzt unten in der Mitte, dort wo die Aktionsbuttons erscheinen. hero_cards sind seine offenen Karten.
- Karten als Rang (A K Q J T 9 8 7 6 5 4 3 2) plus Farbe (s h d c). Schau bei schräg liegenden Karten genau hin.
- hero_to_act ist true genau dann, wenn Aktionsbuttons (Fold/Check/Call/Raise) sichtbar sind.
- to_call ist der Betrag, den Hero zum Mitgehen zahlen muss (steht meist auf dem Call-Button), 0 wenn Check möglich ist.
- pot ist der angezeigte Pot. big_blind nur, wenn die Blinds erkennbar sind.
- hero_dealer ist true, wenn der Dealer-Button (D) an Heros Platz liegt.
- facing_raise: preflop true, wenn vor Hero jemand erhöht hat. Sonst false. Wenn unklar: null.
- players: alle Gegner. in_hand ist false, wenn der Spieler gefoldet hat oder keine Karten hat.
  last_action: fold, check, call, bet, raise, allin oder null.
- Was nicht lesbar ist: null. Nicht raten."""

VOICE_SYSTEM = """Du bist Poker-Companion und Coach: ruhig, klar, mit trockenem Humor in kleiner Dosis. \
Du sitzt neben dem Spieler (Texas Hold'em) und siehst über die App mit.

Sprache: Deutsch, du-Form. Poker-Begriffe bleiben englisch (Call, Raise, Fold, Check, Flop, Pot Odds). \
Deine Antwort wird vorgelesen: höchstens zwei kurze Sätze, keine Listen, kein Markdown, keine Kartensymbole. \
Nur wenn der Spieler ausdrücklich mehr wissen will, darfst du länger werden.

Zahlen: Equity, Pot Odds und Leitplanken rechnet die App und gibt sie dir in eckigen Klammern mit. \
Verwende diese Zahlen. Schätze keine eigenen Prozentwerte. Wenn dir eine Zahl fehlt, sag das.

Strategie: Der Spieler hat ein Strategieprofil eingestellt. Bleib innerhalb der Leitplanken. Wenn du \
abweichen würdest, sag in einem Satz warum, aber empfiehl die Aktion innerhalb der Leitplanken.

Steuerzeilen (werden nicht vorgelesen):
- Beginnt die Nachricht mit [ENTSCHEIDUNG], ist der Spieler am Zug. Deine Antwort beginnt dann mit genau \
einer Zeile [[EMPFEHLUNG <FOLD|CHECK|CALL|RAISE|ALL-IN> <Betrag oder ->]], danach die gesprochene \
Begründung, die mit der Aktion beginnt.
- Bittet der Spieler dich, vorsichtiger, aggressiver, tighter oder looser zu spielen oder mehr oder weniger \
zu bluffen, füge eine Zeile [[STRATEGIE handauswahl=N aggression=N bluff=N]] hinzu, nur mit den geänderten \
Reglern. Skalen: handauswahl 1 (sehr tight, wenige Hände) bis 5 (sehr loose, viele Hände), aggression 1 \
(passiv) bis 5 (sehr aggressiv), bluff 1 (nie) bis 5 (oft). Die aktuellen Werte stehen unter [Strategie]. \
Vorsichtiger heißt: Werte senken.
- Will der Spieler mehr oder weniger Ansagen, füge [[GESPRAECHIGKEIT still|normal|viel]] hinzu."""


class BrainError(Exception):
    pass


def encode_image(img: Image.Image, max_width: int) -> str:
    """Resize + JPEG encode for transfer."""
    w, h = img.size
    if w > max_width:
        img = img.resize((max_width, int(h * max_width / w)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def extract_json(text: str) -> dict | None:
    """The first JSON object in a model answer, tolerant of surrounding text or code fences."""
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return None


def find_claude() -> str | None:
    """Locate the Claude Code binary. A GUI bundle only has a minimal PATH, so look in the usual places."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in CLAUDE_CANDIDATES:
        path = os.path.expanduser(candidate)
        if os.access(path, os.X_OK):
            return path
    return None


def _clean_env() -> dict:
    # Without the parent's CLAUDE* variables the child behaves like a standalone launch.
    return {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}


def cli_logged_in(binary: str) -> bool:
    try:
        out = subprocess.run([binary, "auth", "status"], capture_output=True, text=True,
                             encoding="utf-8", timeout=15, env=_clean_env()).stdout
        return bool((extract_json(out) or {}).get("loggedIn"))
    except (OSError, subprocess.SubprocessError) as e:
        L.warning(f"claude auth status fehlgeschlagen: {e}")
        return False


class CliSession:
    """One long-lived `claude -p` process. Keeps its conversation until restarted."""

    def __init__(self, binary: str, model: str, system: str, effort: str | None = None,
                 thinking: bool = True):
        self._cmd = [binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                     "--verbose", "--include-partial-messages", "--model", model, "--tools", "",
                     "--safe-mode", "--strict-mcp-config", "--disable-slash-commands",
                     "--no-session-persistence", "--system-prompt", system]
        if effort:
            self._cmd += ["--effort", effort]
        if not thinking:
            self._cmd += ["--settings", json.dumps({"alwaysThinkingEnabled": False})]
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.turns = 0

    def start(self):
        """Spawn the process ahead of the first turn so that turn does not pay the start-up."""
        with self._lock:
            if self._proc is None:
                self._spawn()

    def _spawn(self):
        cwd = os.path.expanduser("~/.poker-trainer")
        os.makedirs(cwd, exist_ok=True)
        self._proc = subprocess.Popen(
            self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=open(CLAUDE_LOG, "a"), text=True, encoding="utf-8", bufsize=1,
            env=_clean_env(), cwd=cwd)
        self.turns = 0

    def restart(self):
        with self._lock:
            self._stop()
            self._spawn()

    def ask(self, text: str, image_b64: str | None = None, on_delta=None, cancelled=None) -> str:
        """Send one user turn and return the full answer. `on_delta(text)` gets the stream.

        When `cancelled()` turns true the rest of the answer is still read (the pipe must be
        drained to keep the session in sync) but no longer delivered.
        """
        content = [{"type": "text", "text": text}]
        if image_b64:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg", "data": image_b64}})
        line = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._spawn()
            try:
                self._proc.stdin.write(line + "\n")
                self._proc.stdin.flush()
            except OSError as e:
                raise BrainError(f"claude nicht erreichbar: {e}")
            collected = ""
            for raw in self._proc.stdout:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "stream_event":
                    delta = event.get("event", {}).get("delta", {})
                    if delta.get("type") == "text_delta":
                        collected += delta.get("text", "")
                        if on_delta and not (cancelled and cancelled()):
                            on_delta(delta.get("text", ""))
                elif kind == "result":
                    self.turns += 1
                    if event.get("is_error"):
                        raise BrainError(str(event.get("result"))[:300])
                    return collected or str(event.get("result") or "")
            raise BrainError(f"claude-Prozess beendet, siehe {CLAUDE_LOG}")

    def _stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                self._proc.kill()
        self._proc = None

    def close(self):
        with self._lock:
            self._stop()


class CliBackend:
    name = "claude -p"

    def __init__(self, binary: str, cfg: dict):
        self._width = int(cfg.get("watch_width", 1200))
        self._eyes = CliSession(binary, cfg.get("watch_model", "haiku"), EYES_SYSTEM, thinking=False)
        self._voice = CliSession(binary, cfg.get("brain_model", "sonnet"), VOICE_SYSTEM, effort="low")
        self._seed = ""
        # warm both processes so the first read does not pay the start-up
        threading.Thread(target=self._eyes.start, daemon=True).start()
        threading.Thread(target=self._voice.start, daemon=True).start()
        L.info(f"CLI-Backend: eyes={cfg.get('watch_model', 'haiku')}, voice={cfg.get('brain_model', 'sonnet')}")

    def read_table(self, img: Image.Image) -> dict | None:
        answer = self._eyes.ask("Lies den Tisch.", encode_image(img, self._width))
        return extract_json(answer)

    def new_hand(self):
        """Old screenshots of a finished hand are dead weight: start the eyes with a fresh context."""
        if self._eyes.turns:
            threading.Thread(target=self._eyes.restart, daemon=True).start()

    def ask(self, text: str, img: Image.Image | None = None, on_delta=None, cancelled=None) -> str:
        if self._seed:
            text, self._seed = f"[Bisherige Session]\n{self._seed}\n\n{text}", ""
        image = encode_image(img, 800) if img is not None else None
        return self._voice.ask(text, image, on_delta, cancelled)

    @property
    def voice_turns(self) -> int:
        return self._voice.turns

    def reset_conversation(self, seed: str = ""):
        """Start the voice with an empty context; `seed` carries over what should be remembered."""
        self._seed = seed
        threading.Thread(target=self._voice.restart, daemon=True).start()

    def close(self):
        self._eyes.close()
        self._voice.close()


def make_backend(cfg: dict, api_key: str = ""):
    """Pick the backend: 'cli', 'api' or 'auto' (CLI if installed and logged in, else API)."""
    choice = cfg.get("backend", "auto")
    if choice in ("auto", "cli"):
        binary = find_claude()
        if binary and cli_logged_in(binary):
            return CliBackend(binary, cfg)
        if choice == "cli":
            raise BrainError("claude ist nicht installiert oder nicht eingeloggt (claude auth login)")
        L.info("claude nicht verfügbar, nutze API-Key")
    if not api_key:
        raise BrainError("Weder claude (eingeloggt) noch ein API-Key vorhanden")
    import analyzer
    return analyzer.ApiBackend(api_key, cfg.get("model", "claude-sonnet-4-6"), EYES_SYSTEM, VOICE_SYSTEM)

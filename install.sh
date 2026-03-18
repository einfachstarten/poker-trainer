#!/bin/bash
set -e

echo "♠️  Poker Trainer — Installation"
echo "================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Python prüfen
echo "→ Prüfe Python..."
if command -v /opt/homebrew/bin/python3 &>/dev/null; then
    PYTHON=/opt/homebrew/bin/python3
elif command -v python3.13 &>/dev/null; then
    PYTHON=python3.13
elif command -v python3.12 &>/dev/null; then
    PYTHON=python3.12
elif command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
else
    echo "⚠️  Kein Python 3.11+ gefunden. Installiere via Homebrew..."
    if ! command -v brew &>/dev/null; then
        echo "Homebrew nicht gefunden. Installiere Homebrew zuerst:"
        echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        exit 1
    fi
    brew install python@3.13 python-tk@3.13
    PYTHON=/opt/homebrew/bin/python3.13
fi

PY_VERSION=$($PYTHON --version 2>&1)
echo "  Gefunden: $PY_VERSION"

# 2. tkinter prüfen
echo "→ Prüfe tkinter..."
if ! $PYTHON -c "import tkinter" 2>/dev/null; then
    echo "  tkinter fehlt, installiere..."
    brew install python-tk@3.13 2>/dev/null || brew install python-tk 2>/dev/null || true
fi

# 3. Virtual Environment
echo "→ Erstelle Virtual Environment..."
$PYTHON -m venv .venv
source .venv/bin/activate

# 4. Dependencies
echo "→ Installiere Dependencies..."
pip install --quiet anthropic Pillow numpy pyobjc-framework-Quartz pyobjc-framework-Cocoa rumps

# 5. API Key
echo ""
CONFIG_DIR="$HOME/.poker-trainer"
CONFIG_FILE="$CONFIG_DIR/config.json"
mkdir -p "$CONFIG_DIR"

if [ -f "$CONFIG_FILE" ] && grep -q "api_key" "$CONFIG_FILE" && ! grep -q '"api_key": ""' "$CONFIG_FILE"; then
    echo "✓ API Key bereits konfiguriert"
else
    echo "Du brauchst einen Anthropic API Key."
    echo "  → https://console.anthropic.com → API Keys"
    echo ""
    read -p "API Key eingeben (sk-ant-...): " API_KEY
    if [ -n "$API_KEY" ]; then
        cat > "$CONFIG_FILE" << EOF
{
  "api_key": "$API_KEY",
  "model": "claude-sonnet-4-6",
  "change_threshold": 0.05,
  "debounce_seconds": 1.5,
  "capture_interval": 1.0
}
EOF
        echo "✓ API Key gespeichert in $CONFIG_FILE"
    else
        echo "⚠️  Kein Key eingegeben. Trage ihn später ein:"
        echo "    $CONFIG_FILE"
    fi
fi

# 6. Accessibility-Berechtigung
echo ""
echo "================================"
echo "✓ Installation abgeschlossen!"
echo ""
echo "WICHTIG: Poker Trainer braucht Accessibility-Berechtigung für den Hotkey (F1)."
echo "  → Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen"
echo "  → Terminal (oder iTerm) hinzufügen"
echo ""
echo "Starten mit:"
echo "  ./run.sh"
echo ""
echo "Bedienung:"
echo "  F1 = Analyse (Action, Hand, Pot Odds, Equity)"
echo "  F2 = Neue Runde (Gegner-History löschen)"
echo "  F3 = Detail laden (Begründung, Board, Gegner)"
echo ""

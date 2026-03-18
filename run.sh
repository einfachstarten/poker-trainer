#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "Erst installieren: ./install.sh"
    exit 1
fi

echo "♠️  Poker Trainer startet..."
echo "  → F1 drücken zum Analysieren"
echo "  → Ctrl+C zum Beenden"
echo ""

.venv/bin/python main.py

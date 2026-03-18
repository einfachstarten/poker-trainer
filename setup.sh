#!/bin/bash
# Poker Trainer — One-Line Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/einfachstarten/poker-trainer/main/setup.sh | bash
set -e

INSTALL_DIR="$HOME/poker-trainer"

echo "♠️  Poker Trainer — Setup"
echo ""

# Check git
if ! command -v git &>/dev/null; then
    echo "Git nicht gefunden. Installiere Xcode Command Line Tools..."
    xcode-select --install
    echo "Bitte nach der Installation erneut ausführen."
    exit 1
fi

# Clone or update
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "→ Update vorhandene Installation..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "→ Lade Poker Trainer herunter..."
    git clone https://github.com/einfachstarten/poker-trainer.git "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
chmod +x install.sh run.sh

echo ""
echo "→ Starte Installation..."
echo ""
./install.sh

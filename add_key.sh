#!/bin/bash
# Poker Trainer — packt den API Key in eine fertige DMG
#
#   ./add_key.sh intel         DMG des neuesten Releases für Macs mit Intel-Chip
#   ./add_key.sh apple         DMG des neuesten Releases für Macs mit Apple-Chip
#   ./add_key.sh <datei.dmg>   eine selbst gebaute DMG (build_app.sh)
#
# Der Key kommt aus ~/.poker-trainer/config.json, das Ergebnis liegt in
# dist/Installation. Diese DMG nur persönlich weitergeben, nie hochladen.
set -euo pipefail

RELEASES="https://github.com/einfachstarten/poker-trainer/releases/latest/download"

case "${1:-}" in
    intel) NAME="PokerTrainer-Intel" ;;
    apple) NAME="PokerTrainer-Apple-Chip" ;;
    *.dmg) NAME="$(basename "$1" .dmg)" ;;
    *) echo "Aufruf: ./add_key.sh intel | apple | <datei.dmg>"; exit 1 ;;
esac

REPO="$(git rev-parse --show-toplevel)"
WORK="$REPO/build/key"
OUT="$REPO/dist/Installation"
STAGE="$WORK/dmg"
APP="$STAGE/Poker Trainer.app"
KEY_FILE="$APP/Contents/Resources/api_key"

echo "♠️  Poker Trainer — DMG mit API Key"
echo ""

rm -rf "$WORK"
mkdir -p "$STAGE" "$OUT"
if [ -f "$1" ]; then
    cp "$1" "$WORK/$NAME.dmg"
else
    echo "→ Lade $NAME.dmg vom neuesten Release..."
    curl -fL --progress-bar -o "$WORK/$NAME.dmg" "$RELEASES/$NAME.dmg"
fi

echo "→ Packe API Key ein..."
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$WORK/mnt" "$WORK/$NAME.dmg"
trap 'hdiutil detach -quiet "$WORK/mnt" 2>/dev/null || true' EXIT
cp -R "$WORK/mnt/Poker Trainer.app" "$STAGE/"
cp "$WORK/mnt/INSTALLATION.txt" "$STAGE/"
hdiutil detach -quiet "$WORK/mnt"
ln -s /Applications "$STAGE/Applications"

if ! plutil -extract api_key raw -o "$KEY_FILE" "$HOME/.poker-trainer/config.json" >/dev/null 2>&1 \
        || ! grep -q . "$KEY_FILE"; then
    echo "Kein api_key in ~/.poker-trainer/config.json"
    exit 1
fi

echo "→ Signiere (ad hoc)..."
codesign --force --deep --sign - "$APP" 2>/dev/null
codesign --verify --deep --strict "$APP"

echo "→ Erstelle DMG..."
DMG="$NAME-mit-Key.dmg"
hdiutil create -quiet -volname "Poker Trainer" -srcfolder "$STAGE" -ov -format UDZO "$OUT/$DMG"
cp "$STAGE/INSTALLATION.txt" "$OUT/"

echo ""
echo "✓ Fertig: $OUT"
echo "    $DMG ($(du -h "$OUT/$DMG" | cut -f1 | tr -d ' '))"
echo "    INSTALLATION.txt"
echo ""
echo "Die DMG enthält den API Key: nur persönlich weitergeben, nicht hochladen."

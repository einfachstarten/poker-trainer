#!/bin/bash
# Poker Trainer — baut die App und den Installationsordner dist/Installation
#
#   ./build_app.sh              DMG ohne Key (App fragt beim ersten Start danach)
#   ./build_app.sh --with-key   DMG mit dem API Key aus ~/.poker-trainer/config.json
#                               (nur persönlich weitergeben, nie öffentlich hochladen)
#   ./build_app.sh [...] <ref>  baut einen anderen Stand, z.B. main oder v1.4.0
#
# Gebaut wird immer ein committeter Stand (Standard: HEAD), nicht das Arbeitsverzeichnis.
set -euo pipefail

WITH_KEY=0
REF=HEAD
for arg in "$@"; do
    case "$arg" in
        --with-key) WITH_KEY=1 ;;
        *) REF="$arg" ;;
    esac
done

REPO="$(git rev-parse --show-toplevel)"
PY="$REPO/.venv/bin/python"
BUILD="$REPO/build"
SRC="$BUILD/src"
APP="$REPO/dist/Poker Trainer.app"
OUT="$REPO/dist/Installation"
RES="$APP/Contents/Resources"

echo "♠️  Poker Trainer — App-Build"
echo ""

if [ ! -x "$PY" ]; then
    echo "Kein .venv gefunden. Erst installieren: ./install.sh"
    exit 1
fi
"$PY" -c "import py2app" 2>/dev/null || "$PY" -m pip install --quiet py2app

echo "→ Stand: $(git -C "$REPO" log -1 --format='%h %s' "$REF")"
if [ "$REF" = HEAD ] && [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]; then
    echo "  Hinweis: Uncommittete Änderungen werden nicht mitgebaut."
fi
rm -rf "$BUILD" "$APP" "$OUT"
mkdir -p "$SRC" "$OUT"
git -C "$REPO" archive "$REF" | tar -x -C "$SRC"

echo "→ Baue App (py2app, dauert ein bis zwei Minuten)..."
if ! (cd "$SRC" && "$PY" setup_app.py py2app --dist-dir "$REPO/dist" </dev/null >"$BUILD/py2app.log" 2>&1); then
    tail -30 "$BUILD/py2app.log"
    echo "Build fehlgeschlagen, ganzes Protokoll: $BUILD/py2app.log"
    exit 1
fi

DMG="Poker Trainer.dmg"
if [ "$WITH_KEY" = 1 ]; then
    echo "→ Packe API Key ein..."
    "$PY" - "$RES/api_key" <<'EOF'
import json, os, sys
with open(os.path.expanduser("~/.poker-trainer/config.json")) as f:
    key = json.load(f).get("api_key", "")
if not key:
    sys.exit("Kein api_key in ~/.poker-trainer/config.json")
with open(sys.argv[1], "w") as f:
    f.write(key)
EOF
    DMG="Poker Trainer (mit Key).dmg"
fi

echo "→ Signiere (ad hoc)..."
if ! codesign --force --deep --sign - "$APP" 2>"$BUILD/codesign.log"; then
    cat "$BUILD/codesign.log"
    exit 1
fi
codesign --verify --deep --strict "$APP"

# Der Selbsttest lädt alle Module mit dem Python aus der App. Die Sandbox sperrt
# Homebrew und das venv, so fällt auf, was auf einem frischen Mac fehlen würde.
echo "→ Selbsttest ohne Zugriff auf Homebrew und venv..."
VENV="$(cd "$REPO/.venv" && pwd -P)"
env -i HOME="$BUILD/home" PATH=/usr/bin:/bin RESOURCEPATH="$RES" PYTHONHOME="$RES" PYTHONDONTWRITEBYTECODE=1 \
    sandbox-exec -p "(version 1)(allow default)(deny file-read* (subpath \"/opt/homebrew\") (subpath \"/usr/local\") (subpath \"$VENV\") (subpath \"$SRC\"))" \
    "$APP/Contents/MacOS/python" - "$RES" <<'EOF'
import os, sys
res = sys.argv[1]
sys.path.insert(0, res)
import launcher
launcher._setup_tk()
sys.path.insert(0, launcher.BUNDLED_APP)
import log
log.setup = lambda: None  # das Protokoll einer laufenden App nicht überschreiben
import main               # zieht alle App-Module und Bibliotheken nach
import tkinter
root = tkinter.Tk()       # scheitert, wenn die Tcl/Tk-Skripte fehlen
assert root.tk.eval("info library").startswith(res), root.tk.eval("info library")
root.destroy()
import io
from PIL import Image
Image.new("RGB", (8, 8)).save(io.BytesIO(), "JPEG")
import anthropic
anthropic.Anthropic(api_key="x")
print(f"  Version {main.VERSION}: alle Module geladen, Tk startet")
EOF

echo "→ Erstelle DMG..."
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "$SRC/INSTALLATION.txt" "$STAGE/"
cp "$SRC/INSTALLATION.txt" "$OUT/"
if ! hdiutil create -volname "Poker Trainer" -srcfolder "$STAGE" -ov -format UDZO "$OUT/$DMG" >"$BUILD/hdiutil.log" 2>&1; then
    cat "$BUILD/hdiutil.log"
    exit 1
fi

echo ""
echo "✓ Fertig: $OUT"
echo "    $DMG ($(du -h "$OUT/$DMG" | cut -f1 | tr -d ' '))"
echo "    INSTALLATION.txt"
if [ "$WITH_KEY" = 1 ]; then
    echo ""
    echo "Die DMG enthält den API Key: nur persönlich weitergeben, nicht hochladen."
fi

#!/bin/bash
# Poker Trainer — baut die App und den Installationsordner dist/Installation
#
#   ./build_app.sh          baut den Stand HEAD für den Chip dieses Macs
#   ./build_app.sh <ref>    baut einen anderen Stand, z.B. main oder v1.4.1
#
# Die App läuft nur auf dem Chip, für den sie gebaut wurde (Apple-Chip oder
# Intel). GitHub baut bei jedem Release beide Varianten und hängt sie an das
# Release (.github/workflows/build.yml). Den API Key packt add_key.sh dazu.
#
# Braucht uv. Gebaut wird immer ein committeter Stand, nicht das Arbeitsverzeichnis.
set -euo pipefail

# Eigenständiges Python von uv. Das Python von Homebrew taugt hier nicht: es
# läuft nur auf der macOS-Version, auf der es installiert wurde.
PYTHON_VERSION=3.13.12
MIN_MACOS=12.0   # ältestes macOS, auf dem die App laufen soll

REF="${1:-HEAD}"
ARCH="$(uname -m)"
case "$ARCH" in
    arm64)  CHIP="Apple-Chip"; CHIP_TEXT="Apple-Chip (M1 oder neuer)"; PLATFORM=aarch64-apple-darwin ;;
    x86_64) CHIP="Intel";      CHIP_TEXT="Intel-Chip";                 PLATFORM=x86_64-apple-darwin ;;
    *) echo "Unbekannter Chip: $ARCH"; exit 1 ;;
esac

REPO="$(git rev-parse --show-toplevel)"
BUILD="$REPO/build"
SRC="$BUILD/src"
PY="$BUILD/venv/bin/python"
APP="$REPO/dist/Poker Trainer.app"
OUT="$REPO/dist/Installation"
RES="$APP/Contents/Resources"
DMG="PokerTrainer-$CHIP.dmg"

echo "♠️  Poker Trainer — App-Build ($CHIP, ab macOS ${MIN_MACOS%.0})"
echo ""

if ! command -v uv >/dev/null; then
    echo "uv nicht gefunden. Installieren: brew install uv"
    exit 1
fi

echo "→ Stand: $(git -C "$REPO" log -1 --format='%h %s' "$REF")"
if [ "$REF" = HEAD ] && [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]; then
    echo "  Hinweis: Uncommittete Änderungen werden nicht mitgebaut."
fi
rm -rf "$BUILD" "$APP" "$OUT"
mkdir -p "$SRC" "$OUT"
git -C "$REPO" archive "$REF" | tar -x -C "$SRC"

echo "→ Richte Python $PYTHON_VERSION und die Bibliotheken ein..."
uv venv --quiet --managed-python --python "$PYTHON_VERSION" "$BUILD/venv"
# Die Mindestversion bestimmt, welche Variante einer Bibliothek uv auswählt.
MACOSX_DEPLOYMENT_TARGET="$MIN_MACOS" uv pip install --quiet --python "$PY" --python-platform "$PLATFORM" \
    --only-binary :all: --no-binary rumps --no-deps -r "$SRC/requirements-build.txt"
uv pip check --quiet --python "$PY"

echo "→ Baue App (py2app, dauert ein bis zwei Minuten)..."
if ! (cd "$SRC" && MIN_MACOS="$MIN_MACOS" "$PY" setup_app.py py2app --dist-dir "$REPO/dist" </dev/null >"$BUILD/py2app.log" 2>&1); then
    tail -30 "$BUILD/py2app.log"
    echo "Build fehlgeschlagen, ganzes Protokoll: $BUILD/py2app.log"
    exit 1
fi

# py2app kopiert das zweite Programm (es startet die Regions-Auswahl) unverändert.
# Es sucht die Python-Bibliothek deshalb in Contents/lib statt in Contents/Frameworks.
# Der neue Suchpfad ist genau so lang wie der alte: Für einen längeren ist im
# Kopf der Intel-Datei kein Platz.
if ! install_name_tool -rpath "@executable_path/../lib" "@loader_path/../Frameworks" "$APP/Contents/MacOS/python" 2>"$BUILD/install_name_tool.log"; then
    cat "$BUILD/install_name_tool.log"
    exit 1
fi

# Jede Programmdatei in der App muss für diesen Chip gebaut sein, darf kein
# neueres macOS verlangen als MIN_MACOS und darf nur Bibliotheken laden, die in
# der App liegen oder zu macOS gehören. Sonst läuft die App nur auf diesem Mac.
echo "→ Prüfe die Programmdateien..."
"$PY" - "$APP" "$ARCH" "$MIN_MACOS" <<'EOF'
import os, subprocess, sys

app, arch, limit = sys.argv[1:4]
exe_dir = os.path.join(app, "Contents", "MacOS")
as_tuple = lambda version: tuple(int(x) for x in version.split("."))
count, problems = 0, []
for root, _, files in os.walk(app):
    for name in files:
        path = os.path.join(root, name)
        if os.path.islink(path):
            continue
        with open(path, "rb") as f:
            if f.read(4) not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                continue  # keine Programmdatei (Mach-O)
        count += 1
        rel = os.path.relpath(path, app)
        out = subprocess.run(["otool", "-arch", arch, "-l", path], capture_output=True, text=True).stdout
        if "Load command" not in out:
            problems.append(f"{rel}: nicht für {arch} gebaut")
            continue
        cmd, libs, rpaths = None, [], []
        for line in out.splitlines():
            key, _, value = line.strip().partition(" ")
            value = value.split(" (offset")[0]
            if key == "cmd":
                cmd = value
            elif key == "minos" or (key == "version" and cmd == "LC_VERSION_MIN_MACOSX"):
                if as_tuple(value) > as_tuple(limit):
                    problems.append(f"{rel}: braucht macOS {value}")
            elif key == "name" and cmd in ("LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB"):
                libs.append(value)
            elif key == "path" and cmd == "LC_RPATH":
                rpaths.append(value)
        resolve = lambda p: p.replace("@loader_path", os.path.dirname(path)).replace("@executable_path", exe_dir)
        for lib in libs:
            if lib.startswith(("/usr/lib/", "/System/")):
                continue  # gehört zu macOS
            if lib.startswith("@rpath/"):
                found = any(os.path.exists(os.path.join(resolve(r), lib[len("@rpath/"):])) for r in rpaths)
            else:
                found = lib.startswith("@") and os.path.exists(resolve(lib))
            if not found:
                problems.append(f"{rel}: lädt {lib}, das liegt nicht in der App")
if problems:
    sys.exit("\n".join(problems))
print(f"  {count} Dateien: alle für {arch}, ab macOS {limit}, alle Bibliotheken in der App")
EOF

echo "→ Signiere (ad hoc)..."
if ! codesign --force --deep --sign - "$APP" 2>"$BUILD/codesign.log"; then
    cat "$BUILD/codesign.log"
    exit 1
fi
codesign --verify --deep --strict "$APP"

# Der Selbsttest läuft mit dem Python aus der App. Die Sandbox sperrt Homebrew,
# das venv und das Python von uv, so fällt auf, was auf einem frischen Mac
# fehlen würde.
echo "→ Selbsttest ohne Zugriff auf Homebrew, venv und uv..."
VENV="$(cd "$BUILD/venv" && pwd -P)"
UV_PYTHONS="$(cd "$(uv python dir)" && pwd -P)"
app_python() {
    env -i HOME="$BUILD/home" PATH=/usr/bin:/bin RESOURCEPATH="$RES" PYTHONHOME="$RES" PYTHONDONTWRITEBYTECODE=1 \
        sandbox-exec -p "(version 1)(allow default)(deny file-read* (subpath \"/opt/homebrew\") (subpath \"/usr/local\") (subpath \"$VENV\") (subpath \"$UV_PYTHONS\") (subpath \"$SRC\"))" \
        "$APP/Contents/MacOS/python" - "$RES"
}

app_python <<'EOF'
import io, os, sys
res = sys.argv[1]
sys.path.insert(0, res)
import launcher
sys.path.insert(0, launcher.BUNDLED_APP)
import log
log.setup = lambda: None  # das Protokoll einer laufenden App nicht überschreiben
import main               # zieht alle App-Module und Bibliotheken nach
import detector           # hängt (noch) nicht an main, bringt numpy mit
from PIL import Image
Image.new("RGB", (8, 8)).save(io.BytesIO(), "JPEG")
import ssl                # Zertifikate für den Update-Check
ssl.create_default_context(cafile=os.path.join(res, "openssl.ca", "cert.pem"))
import anthropic
anthropic.Anthropic(api_key="x")
print(f"  Version {main.VERSION}: alle Module geladen")
EOF

# Die Regions-Auswahl ist auch in der App ein eigenes Programm. Hier wird sie
# einmal durchgespielt: Maus drücken, ziehen, loslassen.
app_python <<'EOF'
import contextlib, io, json, os, runpy, sys, tkinter
res = sys.argv[1]
sys.path.insert(0, res)
import launcher
launcher._setup_tk()
sys.path.insert(0, launcher.BUNDLED_APP)

def played_mouse(root):
    canvas = root.winfo_children()[0]
    assert root.tk.eval("info library").startswith(res), root.tk.eval("info library")
    root.update()
    for event, x, y in (("<ButtonPress-1>", 100, 120), ("<B1-Motion>", 300, 260), ("<ButtonRelease-1>", 300, 260)):
        canvas.event_generate(event, x=x, y=y)
        root.update()

tkinter.Tk.mainloop = played_mouse
answer = io.StringIO()
try:
    with contextlib.redirect_stdout(answer):
        runpy.run_path(os.path.join(launcher.BUNDLED_APP, "selector.py"), run_name="__main__")
except SystemExit:
    pass
region = json.loads(answer.getvalue())
assert region == {"x": 100, "y": 120, "w": 200, "h": 140}, region
print("  Regions-Auswahl funktioniert")
EOF

echo "→ Erstelle DMG..."
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
sed -e "s/@CHIP@/$CHIP_TEXT/" -e "s/@MACOS@/${MIN_MACOS%.0}/" "$SRC/INSTALLATION.txt" > "$STAGE/INSTALLATION.txt"
cp "$STAGE/INSTALLATION.txt" "$OUT/"
if ! hdiutil create -volname "Poker Trainer" -srcfolder "$STAGE" -ov -format UDZO "$OUT/$DMG" >"$BUILD/hdiutil.log" 2>&1; then
    cat "$BUILD/hdiutil.log"
    exit 1
fi

echo ""
echo "✓ Fertig: $OUT"
echo "    $DMG ($(du -h "$OUT/$DMG" | cut -f1 | tr -d ' '))"
echo "    INSTALLATION.txt"

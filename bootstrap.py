"""Installs missing packages after an update. Standard library only, runs before anything else.

The updater only pulls new code. When requirements.txt changed with it, the packages
have to follow before the app imports them.
"""

import hashlib
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(APP_DIR, "requirements.txt")
STAMP = os.path.expanduser("~/.poker-trainer/requirements.sha")


def ensure_requirements():
    # A py2app bundle ships its packages and has no pip.
    if getattr(sys, "frozen", False) or not os.path.exists(REQUIREMENTS):
        return
    with open(REQUIREMENTS, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    try:
        with open(STAMP) as f:
            if f.read().strip() == digest:
                return
    except OSError:
        pass
    print("Poker Trainer: installiere neue Pakete ...", flush=True)
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r", REQUIREMENTS])
    if result.returncode != 0:
        print("Paket-Installation fehlgeschlagen. Bitte ./install.sh ausführen.", flush=True)
        return
    os.makedirs(os.path.dirname(STAMP), exist_ok=True)
    with open(STAMP, "w") as f:
        f.write(digest)

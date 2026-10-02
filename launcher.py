"""Entry point of the app bundle (py2app).

The bundle is a fixed runtime: Python, the libraries and a copy of the app
code in Resources/app. An update only replaces the code: main.py downloads the
release to ~/.poker-trainer/app and the launcher starts whichever copy is
newer. The bundle itself never changes, so the macOS permissions granted to it
survive every update.
"""

import json
import locale
import os
import re
import runpy
import shutil
import sys
import time
import traceback

RESOURCES = os.environ.get("RESOURCEPATH") or os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.expanduser("~/.poker-trainer")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
BUNDLED_APP = os.path.join(RESOURCES, "app")
UPDATED_APP = os.path.join(CONFIG_DIR, "app")


def _use_utf8():
    """Make UTF-8 the default encoding of open().

    py2app starts Python in the C locale, where open() defaults to ASCII: the
    log file and the hand history would fail on the first umlaut. (PYTHONUTF8
    has no effect here, the embedded interpreter ignores it.)
    """
    try:
        locale.setlocale(locale.LC_CTYPE, "en_US.UTF-8")
    except locale.Error:
        pass  # better an app with ASCII files than no app


def _version(app_dir):
    """VERSION of the main.py in app_dir as tuple, () if there is none."""
    try:
        with open(os.path.join(app_dir, "main.py"), encoding="utf-8") as f:
            match = re.search(r'^VERSION = "([\d.]+)"', f.read(), re.M)
        return tuple(int(x) for x in match.group(1).split("."))
    except (OSError, AttributeError, ValueError):
        return ()


def _provision_key():
    """Private builds ship the API key in Resources/api_key (build_app.sh --with-key)."""
    key_file = os.path.join(RESOURCES, "api_key")
    if not os.path.exists(key_file):
        return
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    if cfg.get("api_key"):
        return
    with open(key_file) as f:
        cfg["api_key"] = f.read().strip()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def _setup_tk():
    """Point Tk (region selector subprocess) to the Tcl/Tk scripts in the bundle."""
    lib = os.path.join(RESOURCES, "lib")
    for var, prefix in (("TCL_LIBRARY", "tcl"), ("TK_LIBRARY", "tk")):
        for name in os.listdir(lib):
            if re.fullmatch(prefix + r"\d+\.\d+", name):
                os.environ[var] = os.path.join(lib, name)


def _run(app_dir):
    sys.path.insert(0, app_dir)
    sys.argv = [os.path.join(app_dir, "main.py")]
    runpy.run_path(sys.argv[0], run_name="__main__")


def main():
    _use_utf8()
    _provision_key()
    _setup_tk()
    updated = _version(UPDATED_APP) > _version(BUNDLED_APP)
    try:
        _run(UPDATED_APP if updated else BUNDLED_APP)
    except Exception:
        if not updated:
            raise
        # A downloaded update that does not start must not lock the user out:
        # drop it and start again with the code inside the bundle.
        with open(os.path.join(CONFIG_DIR, "launcher.log"), "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Update verworfen:\n{traceback.format_exc()}\n")
        shutil.rmtree(UPDATED_APP, ignore_errors=True)
        exe = os.environ["EXECUTABLEPATH"]
        os.execv(exe, [exe])


if __name__ == "__main__":
    main()

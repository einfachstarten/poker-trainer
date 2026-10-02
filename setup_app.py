"""py2app build script for Poker Trainer. Run it through build_app.sh."""

import glob
import os
import re
import tkinter
import zlib

from setuptools import setup

# The app code. It is traced for dependencies (includes) and shipped as plain
# files in Resources/app, which launcher.py starts.
APP_MODULES = [
    'main', 'analyzer', 'capture', 'config', 'detector', 'history',
    'log', 'overlay', 'selector', 'region_indicator',
]

with open('main.py', encoding='utf-8') as f:
    VERSION = re.search(r'^VERSION = "([\d.]+)"', f.read(), re.M).group(1)

# Tcl/Tk script libraries for the region selector. py2app only copies the
# dylibs; without the scripts Tk does not start on another Mac.
TCL_LIBRARY = tkinter.Tcl().eval('info library')        # .../lib/tcl9.0
# py2app's tkinter recipe starts Tcl without tkinter and does not find it in a venv
os.environ['TCL_LIBRARY'] = TCL_LIBRARY
_tcl_root, _tcl_name = os.path.split(TCL_LIBRARY)
TCL_DIRS = [
    TCL_LIBRARY,
    os.path.join(_tcl_root, 'tk' + _tcl_name[3:]),      # .../lib/tk9.0
    os.path.join(_tcl_root, _tcl_name.split('.')[0]),   # .../lib/tcl9 (msgcat etc.)
]
# The standalone Python keeps the Tcl/Tk libraries next to these folders, and
# _tkinter looks for them two levels above itself: Resources/lib in the bundle.
TCL_DYLIBS = glob.glob(os.path.join(_tcl_root, 'libtcl*.dylib'))

# The standalone Python from uv has zlib built in. py2app expects it as a file
# and copies that file to Resources: hand it launcher.py, which lands there anyway.
if not hasattr(zlib, '__file__'):
    zlib.__file__ = os.path.abspath('launcher.py')

APP = ['launcher.py']
DATA_FILES = [('app', [m + '.py' for m in APP_MODULES] + ['icon.png'])]
OPTIONS = {
    'iconfile': 'app_icon.icns',
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Poker Trainer',
        'CFBundleDisplayName': 'Poker Trainer',
        'CFBundleIdentifier': 'com.einfachstarten.poker-trainer',
        'CFBundleVersion': VERSION,
        'CFBundleShortVersionString': VERSION,
        # Set by build_app.sh, which also checks every binary in the bundle against it
        'LSMinimumSystemVersion': os.environ['MIN_MACOS'],
        'LSUIElement': True,  # menubar app, no dock icon
        'NSAppleEventsUsageDescription': 'Poker Trainer needs accessibility access for hotkeys.',
    },
    'packages': ['anthropic', 'httpx', 'httpcore', 'anyio', 'sniffio', 'certifi', 'h11', 'idna', 'tkinter'],
    'includes': [
        'rumps', 'PIL', 'numpy',
        'objc', 'AppKit', 'Foundation', 'Quartz', 'PyObjCTools',
    ] + APP_MODULES,
    'resources': [('lib', TCL_DIRS + TCL_DYLIBS)],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)

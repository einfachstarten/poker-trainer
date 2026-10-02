"""py2app build script for Poker Trainer. Run it through build_app.sh."""

import os
import re
import sysconfig
import tkinter

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
# dylibs; without the scripts Tk does not start on a Mac without Homebrew.
TCL_LIBRARY = tkinter.Tcl().eval('info library')        # .../lib/tcl9.0
_tcl_root, _tcl_name = os.path.split(TCL_LIBRARY)
TCL_DIRS = [
    TCL_LIBRARY,
    os.path.join(_tcl_root, 'tk' + _tcl_name[3:]),      # .../lib/tk9.0
    os.path.join(_tcl_root, _tcl_name.split('.')[0]),   # .../lib/tcl9 (msgcat etc.)
]

MIN_MACOS = str(sysconfig.get_config_var('MACOSX_DEPLOYMENT_TARGET'))
if '.' not in MIN_MACOS:
    MIN_MACOS += '.0'

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
        # The bundled Python does not run on anything older than its build target
        'LSMinimumSystemVersion': MIN_MACOS,
        'LSUIElement': True,  # menubar app, no dock icon
        'NSAppleEventsUsageDescription': 'Poker Trainer needs accessibility access for hotkeys.',
    },
    'packages': ['anthropic', 'httpx', 'httpcore', 'anyio', 'sniffio', 'certifi', 'h11', 'idna', 'tkinter'],
    'includes': [
        'rumps', 'PIL', 'numpy',
        'objc', 'AppKit', 'Foundation', 'Quartz', 'PyObjCTools',
    ] + APP_MODULES,
    # Python's lzma and Pillow each bring a liblzma.5.dylib. py2app writes both
    # to the same file in Frameworks and corrupts it, so leave Python's out.
    'excludes': ['lzma', '_lzma'],
    'resources': [('lib', TCL_DIRS)],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)

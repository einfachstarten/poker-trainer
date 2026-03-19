"""py2app build script for Poker Trainer."""

from setuptools import setup

APP = ['main.py']
DATA_FILES = [('', ['selector.py', 'icon.png'])]
OPTIONS = {
    'iconfile': 'app_icon.icns',
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Poker Trainer',
        'CFBundleDisplayName': 'Poker Trainer',
        'CFBundleIdentifier': 'com.einfachstarten.poker-trainer',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '12.0',
        'LSUIElement': True,  # menubar app, no dock icon
        'NSAppleEventsUsageDescription': 'Poker Trainer needs accessibility access for hotkeys.',
    },
    'packages': ['anthropic', 'httpx', 'httpcore', 'anyio', 'sniffio', 'certifi', 'h11', 'idna', 'tkinter'],
    'includes': [
        'rumps', 'PIL', 'numpy',
        'objc', 'AppKit', 'Foundation', 'Quartz', 'PyObjCTools',
        'analyzer', 'capture', 'config', 'detector', 'history',
        'log', 'overlay', 'selector',
    ],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)

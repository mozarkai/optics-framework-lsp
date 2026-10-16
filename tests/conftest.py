import os

# A developer's emulator would otherwise be dumped by every server a test starts, and a real download started.
os.environ.setdefault("OPTICS_SCREEN_ELEMENTS", "0")
os.environ.setdefault("OPTICS_AUTO_INSTALL", "0")

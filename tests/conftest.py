import os

# A developer's emulator would otherwise be dumped by every server a test starts.
os.environ.setdefault("OPTICS_SCREEN_ELEMENTS", "0")

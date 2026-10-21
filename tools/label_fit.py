"""Verify every button label fits its rectangle with the hotkey beside it.

Layout tests prove widget *rectangles* do not overlap, but they cannot see a
label overrunning the button it is drawn in - that needs real glyph metrics.
``Button.draw`` blits the label at ``x + 18`` and the hotkey right-aligned at
``rect.right - w - 14``, so the label has this much room:

    rect.width - 18 - (hotkey_width + 14) - trailing margin

This script measures the actual rendered widths and fails loudly on any button
whose text would collide with its hotkey or leave the viewport.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("LOCALAPPDATA", os.path.join(os.getcwd(), ".sdlhome"))

import pygame  # noqa: E402

pygame.font.init()
pygame.display.set_mode((32, 32))

from pongpro.rendering.fonts import FontManager  # noqa: E402

LABEL_SIZE = 22
HOTKEY_SIZE = 14
LABEL_PAD_X = 18
HOTKEY_PAD = 14

# (context, label, hotkey, width) - mirrors scenes/menu.py::_build_menu.
# Kept in step by hand, so the full-width/half-width split here must match
# _build_menu: the two alternate modes share a row, and so do SETTINGS and
# CONTROLS, because the left column has no vertical slack left.
MENU_WIDTH = 452
HALF = (MENU_WIDTH - 8) // 2

BUTTONS = [
    ("menu  play_solo", "1 PLAYER  \u00b7  VS AI", "1", MENU_WIDTH),
    ("menu  play_two", "2 PLAYERS  \u00b7  LOCAL", "2", MENU_WIDTH),
    ("menu  play_focus", "FOCUS MODE", "4", HALF),
    ("menu  play_watch", "AI VS AI", "3", HALF),
    ("menu  settings", "SETTINGS", "F4", HALF),
    ("menu  controls", "CONTROLS", "H", HALF),
    ("menu  replay", "WATCH LAST REPLAY", "R", MENU_WIDTH),
    ("menu  quit", "QUIT", "ESC", MENU_WIDTH),
    ("focus intro", "GOT IT", "", 200),
    ("controls", "BACK TO MENU", "ESC", 920),
]


def main() -> int:
    fonts = FontManager(scale=1.0, cache_size=64)
    failures = 0

    print(f"half-width button = {HALF}px\n")
    print(f"{'button':<20}{'label':<22}{'lbl':>5}{'key':>5}"
          f"{'need':>6}{'room':>6}  status")
    print("-" * 74)

    for context, label, hotkey, width in BUTTONS:
        label_w = fonts.width(label, LABEL_SIZE)
        hotkey_w = fonts.width(hotkey, HOTKEY_SIZE) if hotkey else 0
        # Right-aligned hotkey's left edge is where the label must stop.
        key_left = width - hotkey_w - HOTKEY_PAD if hotkey else width
        room = key_left - LABEL_PAD_X
        needed = label_w
        ok = needed <= room
        if not ok:
            failures += 1
        print(f"{context:<20}{label:<22}{label_w:>5}{hotkey_w:>5}"
              f"{needed:>6}{room:>6}  {'OK' if ok else 'OVERFLOW'}")

    print()
    if failures:
        print(f"FAIL: {failures} label(s) overrun their button")
        return 1
    print(f"PASS: all {len(BUTTONS)} labels fit")
    return 0


if __name__ == "__main__":
    sys.exit(main())

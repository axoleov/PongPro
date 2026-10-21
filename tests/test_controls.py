"""The How-to-Play reference, and the procedural icon behind the window.

Two features that exist purely so a *first-time* player can use the game, and
so the packaged build looks like a product rather than a script.  Both are
easy to let rot, because nothing in normal play exercises them:

* the controls table is hand-transcribed prose sitting next to code that
  actually binds the keys, so the two can drift apart silently - a new
  shortcut gets added to ``gameplay.py`` and the reference never mentions it,
  which is precisely the failure that hurts most (the help is *wrong*, and
  wrong help is worse than none);
* the icon is generated rather than loaded, so it is pure logic that no
  screenshot of the game would ever reveal is broken.

Hence the two odd-looking test classes below: one reads the scene handlers'
own source and compares it against the printed table, and one parses the
emitted ``.ico`` byte-for-byte rather than trusting that it "loaded".
"""

from __future__ import annotations

import re
import struct
import unittest
from pathlib import Path

import pygame

from pongpro.scenes.controls import ELSEWHERE, IN_MATCH

#: pygame key constant -> how the reference card spells it.  Anything missing
#: here is a key the card does not know how to name, which is itself a bug.
_KEY_NAMES: dict[str, str] = {
    "K_1": "1", "K_2": "2", "K_3": "3", "K_4": "4",
    "K_F2": "F2", "K_F3": "F3", "K_F4": "F4",
    "K_ESCAPE": "ESC",
    "K_RETURN": "ENTER",
    "K_SPACE": "SPACE",
    "K_BACKSPACE": "BACKSPACE",
    "K_UP": "\u2191", "K_DOWN": "\u2193",
    "K_LEFT": "\u2190", "K_RIGHT": "\u2192",
    "K_w": "W", "K_s": "S", "K_i": "I", "K_k": "K",
    "K_p": "P", "K_r": "R", "K_h": "H",
}

#: Handlers that must stay in step with the card, as (module, class, methods).
#: ``MenuList`` is included because that is where the arrow keys and ENTER
#: actually live - they are not in ``MenuScene.handle_event``, so a check that
#: only read the scene would wrongly report them as undocumented.  Likewise
#: ``_read_axes`` is listed for the gameplay scene: the paddles are *polled*
#: every step rather than read from KEYDOWN events, so their keys appear
#: nowhere near ``handle_event`` and a naive scan misses all eight of them.
#: The pause scene is excluded on purpose - it offers RESUME and SETTINGS, not
#: new bindings, so there is nothing there for the card to describe.
_SOURCES = (
    ("scenes/gameplay.py", "GameplayScene", ("handle_event", "_read_axes")),
    ("scenes/menu.py", "MenuScene", ("handle_event",)),
    ("rendering/ui.py", "MenuList", ("handle_event",)),
)

#: Keys a handler listens for that the card deliberately stays quiet on.  Each
#: is either a redundant alias (numpad ENTER, both TAB and BACKSPACE to go
#: back) or a raw scancode detail no player needs.  Keeping the list explicit
#: means an *accidental* omission still fails the test - it has to be added
#: here, and adding it here is a visible, reviewable decision.
#: The keys are spelled as the *constants* the regex extracts, so ``K_`` is
#: part of each entry - spelling them without it silently matched nothing and
#: let K_KP_ENTER through as unknown.
_UNDOCUMENTED_OK: dict[str, str] = {
    "K_KP_ENTER": "numpad ENTER; the card documents ENTER",
    "K_TAB": "menu alias for the arrow keys",
    "K_BACKSPACE": "menu alias for ESC",
}


def _method_body(relative: str, class_name: str, method: str) -> str:
    """Return the source of one method, from its ``def`` to the next method.

    Deliberately text-based: the point is to catch a *binding* change, and
    re-importing the classes would only give back the same objects the game
    already runs, which cannot tell us what was written down by hand.
    """
    path = Path(__file__).resolve().parent.parent / "src" / "pongpro" / relative
    lines = path.read_text(encoding="utf-8").splitlines()

    start = None
    for index, line in enumerate(lines):
        # Accept both ``class MenuList:`` and ``class Scene(Scene):`` - the
        # bracket is optional, and insisting on it found nothing in ui.py.
        if line.startswith(f"class {class_name}:") \
                or line.startswith(f"class {class_name}("):
            start = index
            break
    if start is None:
        raise AssertionError(f"{class_name} not found in {relative}")

    body: list[str] = []
    in_method = False
    for line in lines[start + 1:]:
        if line.startswith(f"    def {method}("):
            in_method = True
            body.append(line)
            continue
        if in_method:
            # The method ends at the next top-of-class member (same indent).
            if line.startswith("    def ") or line.startswith("class "):
                break
            body.append(line)
    if not in_method:
        raise AssertionError(
            f"{class_name}.{method} not found in {relative}")
    return "\n".join(body)


def _bound_keys(relative: str, class_name: str,  # type: ignore[no-untyped-def]
                methods: tuple[str, ...]) -> set[str]:
    """Every ``pygame.K_*`` constant the listed methods test against."""
    found: set[str] = set()
    for method in methods:
        body = _method_body(relative, class_name, method)
        found |= set(re.findall(r"pygame\.(K_[A-Za-z0-9_]+)", body))
    unknown = found - _KEY_NAMES.keys() - _UNDOCUMENTED_OK.keys()
    if unknown:
        raise AssertionError(
            f"{class_name} binds keys the reference card cannot name: "
            f"{sorted(unknown)}")
    return {_KEY_NAMES[name] for name in found - _UNDOCUMENTED_OK.keys()}


def _documented_keys() -> set[str]:
    """Every key token printed on the card.

    A row may spell out alternatives in one cell - "ESC / P", "I / K", or the
    arrow cluster "↑ ↓ ← →" - so split on both the slash and any whitespace,
    and drop the empty strings that splitting produces.
    """
    keys: set[str] = set()
    for sections in (IN_MATCH, ELSEWHERE):
        for _heading, rows in sections:
            for token, _description in rows:
                for part in re.split(r"[/\s]+", token):
                    if part:
                        keys.add(part)
    return keys


# ---------------------------------------------------------------------------
# Controls reference
# ---------------------------------------------------------------------------
class ControlsTableTests(unittest.TestCase):
    """The card and the code must describe the same game."""

    def test_every_bound_key_is_documented(self) -> None:
        documented = _documented_keys()
        for relative, class_name, methods in _SOURCES:
            for key in _bound_keys(relative, class_name, methods):
                self.assertIn(
                    key, documented,
                    f"{class_name} handles {key!r} but the controls card "
                    f"never mentions it")

    def test_every_documented_key_is_bound(self) -> None:
        # The reverse direction: a key that nothing handles is a promise the
        # game does not keep, and a player will press it and be confused.
        bound: set[str] = set()
        for relative, class_name, methods in _SOURCES:
            bound |= _bound_keys(relative, class_name, methods)
        # "MOUSE" is a real instruction, just not a key - it is allowed to be
        # documented without a pygame constant behind it.
        unbound = _documented_keys() - bound - {"MOUSE"}
        self.assertEqual(unbound, set(),
                         "the controls card documents keys nothing handles")

    def test_the_focus_paddle_keys_are_named(self) -> None:
        # FOCUS is the mode whose bindings are least guessable (one player,
        # two hands, two alternative key sets), so it is the one a player is
        # most likely to check this screen for.
        documented = " ".join(token for _h, rows in IN_MATCH
                              for token, _d in rows)
        for key in ("W / S", "I / K"):
            self.assertIn(key, documented)

    def test_rows_describe_their_keys(self) -> None:
        # An empty description would render as a pill with nothing beside it.
        for sections in (IN_MATCH, ELSEWHERE):
            for heading, rows in sections:
                self.assertTrue(rows, f"section {heading!r} has no rows")
                for token, description in rows:
                    self.assertTrue(token.strip(), f"{heading}: empty key")
                    self.assertTrue(
                        description.strip(),
                        f"{heading}: {token!r} has no description")

    def test_descriptions_fit_their_column(self) -> None:
        """A long description runs under the other column's key pills.

        Nothing else catches this: the columns are drawn as plain text, so
        the widget-overlap suite in test_layout cannot see them collide.  The
        description starts after a shared pill column 44% of the width across
        (see ``ControlsScene._draw_row``), so it gets the remaining 56%.
        """
        from pongpro.rendering.fonts import FontManager
        from pongpro.scenes.controls import IN_MATCH, PANEL_W

        pygame.init()
        pygame.display.set_mode((32, 32))
        fonts = FontManager(scale=1.0, cache_size=64)

        col_w = PANEL_W // 2 - 60
        available = col_w - int(col_w * 0.44)
        self.assertGreater(available, 100, "description budget implausibly small")

        widest = 0
        for sections in (IN_MATCH, ELSEWHERE):
            for _heading, rows in sections:
                for _token, description in rows:
                    width = fonts.width(description, 14)
                    widest = max(widest, width)
                    self.assertLessEqual(
                        width, available,
                        f"{description!r} is {width}px but only {available}px "
                        f"fit before the other column starts")
        # Guard against the test quietly passing by measuring nothing.
        self.assertGreater(widest, 0)


# ---------------------------------------------------------------------------
# Icon
# ---------------------------------------------------------------------------
class IconRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        # convert_alpha (used when blitting the bloom) needs a display.
        pygame.init()
        pygame.display.set_mode((32, 32))

    def test_renders_at_the_requested_size(self) -> None:
        from pongpro.rendering.icon import render_icon

        for size in (16, 32, 64, 256):
            surf = render_icon(size)
            self.assertEqual(surf.get_size(), (size, size), size)
            self.assertTrue(surf.get_flags() & pygame.SRCALPHA, size)

    def test_the_plate_is_rounded_not_square(self) -> None:
        # The corner must be fully transparent, or the icon gets a white halo
        # against Windows' own rounded window corners.
        from pongpro.rendering.icon import render_icon

        surf = render_icon(128)
        self.assertEqual(surf.get_at((0, 0)).a, 0, "top-left corner is opaque")
        self.assertEqual(surf.get_at((127, 0)).a, 0, "top-right corner opaque")
        self.assertEqual(surf.get_at((0, 127)).a, 0, "bottom-left corner opaque")
        # ...and some interior point is not, so the plate exists at all.  This
        # must avoid the centre line, which is deliberately translucent, so it
        # samples empty plate to the right of the court.
        self.assertEqual(surf.get_at((90, 95)).a, 255, "plate is transparent")

    def test_the_two_paddles_keep_their_colours(self) -> None:
        # Guards the one thing that identifies the mark at small sizes: the
        # P1/P2 pairing.  Sampling samples the paddle *body* rather than its
        # pale core, which is intentionally blended towards white.
        from pongpro.core.constants import Color
        from pongpro.rendering.icon import render_icon

        surf = render_icon(128)
        left = surf.get_at((20, 54))    # left paddle, outside the core
        right = surf.get_at((101, 80))  # right paddle, outside the core
        self.assertGreater(left.g, left.r, "left paddle should read as cyan")
        self.assertGreater(right.r, right.g, "right paddle should read as pink")
        self.assertGreater(right.b, right.g, "right paddle should read as pink")
        self.assertEqual(tuple(left)[:3], tuple(Color.P1)[:3])
        self.assertEqual(tuple(right)[:3], tuple(Color.P2)[:3])

    def test_very_small_sizes_still_render(self) -> None:
        from pongpro.rendering.icon import render_icon

        for size in (8, 12, 16):
            surf = render_icon(size)
            self.assertEqual(surf.get_size(), (size, size), size)


class IconIcoTests(unittest.TestCase):
    """Parse the written .ico by hand - a file that merely loads proves little."""

    def setUp(self) -> None:
        pygame.init()
        pygame.display.set_mode((32, 32))

    @staticmethod
    def _write(tmp: Path, sizes: tuple[int, ...]) -> bytes:
        from pongpro.rendering.icon import write_ico

        return write_ico(tmp, sizes).read_bytes()

    def test_header_counts_the_images(self) -> None:
        import tempfile

        from pongpro.rendering.icon import ICO_SIZES

        with tempfile.TemporaryDirectory() as tmpdir:
            raw = self._write(Path(tmpdir) / "i.ico", ICO_SIZES)
        reserved, kind, count = struct.unpack_from("<HHH", raw, 0)
        self.assertEqual(reserved, 0)
        self.assertEqual(kind, 1, "type 1 means icon, not cursor")
        self.assertEqual(count, len(ICO_SIZES))

    def test_entries_point_at_valid_pixel_blocks(self) -> None:
        import tempfile

        from pongpro.rendering.icon import ICO_SIZES

        with tempfile.TemporaryDirectory() as tmpdir:
            raw = self._write(Path(tmpdir) / "i.ico", ICO_SIZES)

        offset = 6
        for size in ICO_SIZES:
            width, height, _colors, _res, planes, bpp, length, start = \
                struct.unpack_from("<BBBBHHII", raw, offset)
            self.assertEqual(planes, 1)
            self.assertEqual(bpp, 32, "icons are stored as 32-bit BGRA")
            self.assertEqual(width, 0 if size >= 256 else size)
            self.assertEqual(height, 0 if size >= 256 else size)
            # Every block must lie inside the file, and its BITMAPINFOHEADER
            # must agree with the directory entry about the size.
            self.assertLessEqual(start + length, len(raw), f"{size}px block")
            (header_size, bw, bh) = struct.unpack_from("<Iii", raw, start)
            self.assertEqual(header_size, 40)
            self.assertEqual(bw, size)
            self.assertEqual(bh, size * 2, "BMP height counts the AND mask")
            offset += 16

    def test_block_length_covers_the_pixels_it_claims(self) -> None:
        import tempfile

        from pongpro.rendering.icon import ICO_SIZES

        with tempfile.TemporaryDirectory() as tmpdir:
            raw = self._write(Path(tmpdir) / "i.ico", ICO_SIZES)

        offset = 6
        for size in ICO_SIZES:
            *_, length, start = struct.unpack_from("<BBBBHHII", raw, offset)
            pixels = size * size * 4
            # 40-byte BITMAPINFOHEADER + pixels + AND mask, where the mask
            # row is padded to a 4-byte boundary.
            mask_row = ((size + 31) // 32) * 4
            self.assertEqual(length, 40 + pixels + mask_row * size, f"{size}px")
            offset += 16

    def test_pygame_can_reload_what_was_written(self) -> None:
        import tempfile

        from pongpro.rendering.icon import ICO_SIZES

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "i.ico"
            self._write(path, ICO_SIZES)
            surf = pygame.image.load(str(path))
        # pygame loads the first (smallest) frame by default.
        self.assertEqual(surf.get_size()[0], ICO_SIZES[0])

    def test_a_larger_size_is_written_later_in_the_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            raw = self._write(Path(tmpdir) / "i.ico", (16, 256))
        # 256 encodes as byte 0, which is the one case the packing gets wrong
        # if it is written naively.
        width_256 = struct.unpack_from("<B", raw, 6 + 16 + 0)[0]
        self.assertEqual(width_256, 0, "256 is stored as 0 in the .ico entry")


if __name__ == "__main__":
    unittest.main()

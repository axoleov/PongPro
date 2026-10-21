"""The PongPro mark, drawn procedurally at any size.

The project ships **no binary assets** - every sound, trail and backdrop is
synthesised at run time - so the window icon follows the same rule.  Rather
than loading a PNG, the glyph is described in normalised coordinates and
painted onto a surface of whatever size is asked for, which keeps it crisp at
16 px (the taskbar) as well as 256 px (the task manager and the installer).

The same renderer feeds the packaged ``.exe``: ``tools\\make_icon.py`` calls
:func:`write_ico` to emit ``packaging\\pongpro.ico``, which ``pongpro.spec``
picks up.  One description, two consumers - the runtime window icon and the
frozen binary can never drift apart.

Design notes
------------
The mark is a stripped-down frame of the game itself, because that is what it
has to communicate at a glance:

* a near-square dark plate with rounded corners, so it sits inside Windows'
  own corner rounding without a white halo;
* the centre court line, split into dashes - the one shape nobody else owns;
* a cyan paddle and a pink one, the same two colours the HUD uses for P1/P2,
  deliberately offset vertically so the icon reads as *motion* rather than a
  symmetrical logo;
* the ball with a short fading trail, catching the eye at every size.

Every dimension is a fraction of the surface, so nothing has to be re-tuned
per size; the only size-dependent quantity is the rounding radius, which is
clamped to stay visible at 16 px.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pygame

from ..core.constants import Color

#: Sizes written into the packaged ``.ico``.  16/32/48 cover the taskbar,
#: alt-tab and file listing; 256 covers thumbnails and high-DPI views.
ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

#: Plate colours - a vertical gradient, dark enough that the paddles glow.
_PLATE_TOP = (23, 28, 44)
_PLATE_BOTTOM = (9, 11, 18)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int],
          t: float) -> tuple[int, int, int]:
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def _rounded_mask(size: int, radius: int) -> pygame.Surface:
    """White rounded square on transparent - used to clip the plate."""
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255),
                     (0, 0, size, size), border_radius=radius)
    return mask


def _paint_plate(surf: pygame.Surface, size: int) -> None:
    """Vertical gradient, clipped to a rounded square."""
    radius = max(2, int(size * 0.19))
    gradient = pygame.Surface((size, size), pygame.SRCALPHA)
    for y in range(size):
        gradient.fill(_lerp(_PLATE_TOP, _PLATE_BOTTOM, y / max(1, size - 1)),
                      (0, y, size, 1))
    # Multiplying by a white-rounded mask zeroes the alpha outside the
    # corners, which is what actually rounds the plate off; blit()'s third
    # argument is a source rect, not a mask.
    gradient.blit(_rounded_mask(size, radius), (0, 0),
                  special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(gradient, (0, 0))


def _paint_court(surf: pygame.Surface, size: int) -> None:
    """The split centre line - the shape that says 'Pong' with no text."""
    width = max(1, int(size * 0.045))
    x = size // 2 - width // 2
    top, bottom = int(size * 0.14), int(size * 0.86)
    dash = max(2, int(size * 0.09))
    gap = max(2, int(size * 0.07))
    y = top
    while y < bottom:
        seg = min(dash, bottom - y)
        pygame.draw.rect(surf, (*Color.TEXT_DIM, 60), (x, y, width, seg))
        y += dash + gap


def _paint_paddle(surf: pygame.Surface, size: int, *,
                  cx: float, cy: float, color: tuple[int, int, int]) -> None:
    """One glowing paddle, positioned in normalised coordinates."""
    w = max(2, int(size * 0.075))
    h = max(4, int(size * 0.40))
    x = int(size * cx) - w // 2
    y = int(size * cy) - h // 2
    rect = pygame.Rect(x, y, w, h)

    # Soft bloom behind the paddle, so it reads as lit rather than flat.
    glow = pygame.Surface((w + 16, h + 16), pygame.SRCALPHA)
    pygame.draw.rect(glow, (*color, 60), (8, 8, w, h),
                     border_radius=w // 2)
    surf.blit(glow, (rect.x - 8, rect.y - 8))
    pygame.draw.rect(surf, color, rect, border_radius=w // 2)
    # A pale core gives the paddle the same hot centre the HUD paddles have.
    core = Color.blend(color, (255, 255, 255), 0.45)
    inset = max(1, w // 4)
    pygame.draw.rect(surf, core,
                     (rect.x + inset, rect.y + inset + max(1, h // 12),
                      max(1, w - inset * 2), max(1, h - inset * 2 - h // 6)),
                     border_radius=max(1, w // 3))


def _paint_ball(surf: pygame.Surface, size: int) -> None:
    """Ball plus a short fading trail, implying travel from the left."""
    cx, cy = size * 0.585, size * 0.375
    radius = max(2, int(size * 0.095))

    # Trail: three dots receding back towards the left paddle, fading out.
    # Deliberately short - a longer one runs the last dot into the paddle and
    # the icon stops reading as three separate objects.
    for i in range(3, 0, -1):
        t = i / 4.0
        tx = cx - size * 0.085 * i
        ty = cy + size * 0.045 * i
        tr = max(1, int(radius * (1.0 - t) * 0.8))
        alpha = int(160 * (1.0 - t))
        if alpha <= 0 or tr <= 0:
            continue
        pygame.draw.circle(surf, (*Color.GOLD, alpha), (int(tx), int(ty)), tr)

    # A tight bloom rather than a wide one: a large low-alpha gold wash over a
    # near-black plate reads as muddy brown instead of light.
    bloom = pygame.Surface((radius * 3, radius * 3), pygame.SRCALPHA)
    pygame.draw.circle(bloom, (*Color.GOLD, 80), (radius * 3 // 2, radius * 3 // 2),
                       radius * 3 // 2)
    surf.blit(bloom, (int(cx) - radius * 3 // 2, int(cy) - radius * 3 // 2))
    pygame.draw.circle(surf, Color.GOLD, (int(cx), int(cy)), radius)
    pygame.draw.circle(surf, (255, 252, 232),
                       (int(cx), int(cy)), max(1, radius - max(1, size // 64)))


def render_icon(size: int) -> pygame.Surface:
    """Draw the mark at ``size`` x ``size`` with a full alpha channel."""
    size = max(8, int(size))
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    _paint_plate(surf, size)
    _paint_court(surf, size)
    _paint_paddle(surf, size, cx=0.185, cy=0.42, color=Color.P1)
    _paint_paddle(surf, size, cx=0.815, cy=0.62, color=Color.P2)
    _paint_ball(surf, size)
    return surf


def window_icon() -> pygame.Surface:
    """The surface handed to ``pygame.display.set_icon``.

    Rendered at 64 px so downscaling is done once here rather than by the
    window manager, which would otherwise produce a aliased taskbar glyph.
    """
    return render_icon(64)


# --------------------------------------------------------------------------
# .ico serialisation
# --------------------------------------------------------------------------
# pygame can *load* .ico files but not write them (SDL2_image exposes no ICO
# saver), and the frozen build needs a real file on disk for PyInstaller.  The
# format is small enough to emit directly: a 6-byte directory header, one
# 16-byte entry per image, then each image as a BITMAPINFOHEADER plus a 32-bit
# BGRA pixel block plus a 1-bit AND mask.

_BMP_HEADER_SIZE = 40


def _icon_dir(count: int) -> bytes:
    # idReserved=0, idType=1 (icons), idCount.
    return struct.pack("<HHH", 0, 1, count)


def _icon_entry(size: int, data_len: int, offset: int) -> bytes:
    # Width and height are single bytes; 0 means 256.
    byte_size = 0 if size >= 256 else size
    return struct.pack(
        "<BBBBHHII",
        byte_size, byte_size,  # bWidth, bHeight
        0,                     # bColorCount (unused for 32-bit)
        0,                     # bReserved
        1,                     # wPlanes
        32,                    # wBitCount
        data_len,              # dwBytesInRes
        offset,                # dwImageOffset
    )


def _bmp_data(surf: pygame.Surface) -> bytes:
    """One icon image: BITMAPINFOHEADER + BGRA rows + AND mask, bottom-up."""
    width, height = surf.get_size()
    header = struct.pack(
        "<IiiHHIIiiII",
        _BMP_HEADER_SIZE, width, height * 2, 1, 32, 0,
        width * height * 4, 0, 0, 0, 0)

    # BGRA is the layout Windows expects, and rows run bottom-up.
    bgra = pygame.image.tobytes(surf, "BGRA")
    row_bytes = width * 4
    rows = [bgra[y * row_bytes:(y + 1) * row_bytes] for y in range(height)]
    pixels = b"".join(reversed(rows))

    # AND mask: 1 bit per pixel, rows padded to 4 bytes, marked transparent
    # wherever the alpha is below half.  32-bit icons mostly ignore it, but
    # some contexts (older thumbnails, safe-mode previews) still consult it.
    mask_row = ((width + 31) // 32) * 4
    mask = bytearray(mask_row * height)
    raw_alpha = pygame.image.tobytes(surf, "RGBA")[3::4]
    for y in range(height):
        src_row = height - 1 - y  # masks are stored bottom-up too
        for x in range(width):
            if raw_alpha[src_row * width + x] < 128:
                byte_i = y * mask_row + (x >> 3)
                mask[byte_i] |= 0x80 >> (x & 7)
    return header + pixels + bytes(mask)


def write_ico(path: str | Path, sizes: tuple[int, ...] = ICO_SIZES) -> Path:
    """Render every size in ``sizes`` and write them into a multi-size .ico."""
    surfaces = [render_icon(s) for s in sizes]

    entry_table = _icon_dir(len(surfaces))
    # Entries are fixed width, so the first pixel block starts right after
    # the directory: 6 bytes of header plus 16 bytes per image.
    offset = len(entry_table) + 16 * len(surfaces)
    blobs: list[bytes] = []
    for size, surf in zip(sizes, surfaces):
        blob = _bmp_data(surf)
        entry_table += _icon_entry(size, len(blob), offset)
        blobs.append(blob)
        offset += len(blob)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(entry_table + b"".join(blobs))
    return out


__all__ = ["ICO_SIZES", "render_icon", "window_icon", "write_ico"]

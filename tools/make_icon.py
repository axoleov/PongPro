"""Generate ``packaging\\pongpro.ico`` from the procedural mark.

Run before packaging so PyInstaller has a real file to embed (``pongpro.spec``
looks for exactly this path and silently ships a generic icon when it is
absent).  The glyph itself lives in ``pongpro.rendering.icon`` so the packaged
``.exe`` and the running window's taskbar icon are drawn from one description
and can never drift apart:

    python tools\\make_icon.py            # write the .ico
    python tools\\make_icon.py --preview  # also dump a PNG to eyeball
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

pygame.font.init()
pygame.display.set_mode((32, 32))

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packaging" / "pongpro.ico"
PREVIEW = ROOT / "tools" / "shots" / "icon_preview.png"


def main() -> int:
    from pongpro.rendering.icon import ICO_SIZES, render_icon, write_ico

    write_ico(OUT, ICO_SIZES)

    raw = OUT.stat().st_size
    print(f"wrote {OUT.relative_to(ROOT)}  {raw} bytes  sizes={ICO_SIZES}")

    # A .ico is not viewable in place, so also dump a large single-size PNG
    # for eyeballing.  Purely a convenience; not part of the build.
    if "--preview" in sys.argv:
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(render_icon(256), str(PREVIEW))
        print(f"wrote {PREVIEW.relative_to(ROOT)}")

    # Sanity check: reload the file through pygame, which is the same code
    # path the game's own icon loader would use if it ever loaded one.
    loaded = pygame.image.load(str(OUT))
    print(f"verified: pygame reloaded it at {loaded.get_size()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

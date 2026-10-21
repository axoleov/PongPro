"""Package entry point: ``python -m pongpro`` (when the package is importable)."""

from __future__ import annotations

import argparse
import os
import sys


def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pongpro",
                                     description="PongPro - production Pong")
    parser.add_argument("--frames", type=int, default=None,
                        help="run a fixed number of frames then exit (CI smoke)")
    parser.add_argument("--quiet", action="store_true",
                        help="log to file only (no console output)")
    parser.add_argument("--skip-splash", action="store_true",
                        help="jump straight to the main menu")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    args = _parse(argv)

    from .app import Application
    from .core.state_machine import Transition
    from .scenes.menu import MenuScene

    app = Application(max_frames=args.frames, quiet=args.quiet)
    if args.skip_splash:
        app.stack.replace_top(1, MenuScene(), transition=Transition.NONE)
    return app.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

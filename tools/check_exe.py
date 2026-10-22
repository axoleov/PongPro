"""Prove the shipped exe actually starts.

A build that completes is not a build that runs.  The first release compiled
cleanly, staged cleanly, pushed cleanly - and then died on another machine with
``No module named '_socket'`` because git had dropped its ``.pyd`` files.  The
failure happened before the script body ran, so no traceback, no log, nothing
in the build pipeline noticed.

The one signal that survives all of that is the game's own log: ``Application``
writes ``pongpro.log`` on construction, so a non-empty log proves the bootloader
extracted the bundle, the runtime hooks ran, every module imported and pygame
initialised.  A crash before that point leaves no file at all.

Note why "process still running" is deliberately *not* the test: a windowed
PyInstaller build that fails shows an error dialog and sits there waiting for a
click, so a dead-looking machine reports as an alive process.

    python tools\\check_exe.py           headless (dummy SDL, CI-safe)
    python tools\\check_exe.py --real    real window and audio device
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXE = ROOT / "Builds" / "PongPro.exe"
LAUNCH_MARK = "Ready: WINDOW"     # logged once video, audio and scenes are up
EARLY_MARK = "starting"           # written by Application.__init__
DEAD_MARK = "Traceback"           # a crash we can actually quote back


def launch(exe: Path, scratch: Path, real: bool) -> subprocess.Popen:
    env = os.environ.copy()
    # Redirect every writable path so the check never touches a real profile.
    env["LOCALAPPDATA"] = str(scratch)
    env["APPDATA"] = str(scratch)
    if not real:
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
    env.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    # A windowed exe has no stdout to inherit; give it somewhere to land.
    return subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def log_text(scratch: Path) -> str:
    log = scratch / "PongPro" / "logs" / "pongpro.log"
    if not log.exists():
        return ""
    try:
        return log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", nargs="?", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--real", action="store_true",
                        help="use the real display and audio device instead "
                             "of SDL's dummy drivers")
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="seconds to wait for the log (default 60)")
    args = parser.parse_args()

    exe = args.exe.resolve()
    if not exe.exists():
        print(f"missing exe: {exe}")
        return 1

    scratch = Path(tempfile.mkdtemp(prefix="pongpro_check_"))
    mode = "real display" if args.real else "headless (dummy SDL)"
    print(f"exe   : {exe.relative_to(ROOT) if exe.is_relative_to(ROOT) else exe}")
    print(f"size  : {exe.stat().st_size:,} bytes")
    print(f"mode  : {mode}")
    print(f"profile: {scratch}")

    started = time.monotonic()
    proc = launch(exe, scratch, args.real)
    print(f"pid   : {proc.pid}")

    text = ""
    try:
        # Poll rather than sleep: onefile unpacks to temp first, and how long
        # that takes depends entirely on the machine's disk.
        deadline = started + args.timeout
        while time.monotonic() < deadline:
            text = log_text(scratch)
            if LAUNCH_MARK in text:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)

        elapsed = time.monotonic() - started
        print(f"waited: {elapsed:.1f}s")

        def show(why: str) -> None:
            print(why)
            body = [ln for ln in text.splitlines() if ln.strip()]
            if not body:
                print("      (no log file was created at all)")
            for ln in body[-12:]:
                print(f"      {ln}")

        if proc.poll() is not None and EARLY_MARK not in text:
            print(f"FAIL: the process exited with code {proc.returncode} "
                  f"before it could log anything.")
            print("      This is the pre-script failure mode - a missing module,")
            print("      a bad runtime hook, or an unpack error.")
            return 1

        if EARLY_MARK not in text:
            show(f"FAIL: no log after {args.timeout:.0f}s - the game never "
                 "reached Application construction.")
            return 1

        if DEAD_MARK in text:
            show("FAIL: the log contains a traceback:")
            return 1

        if LAUNCH_MARK not in text:
            show("FAIL: logging began but initialisation never completed - "
                 "the game is stuck before the window is ready.")
            return 1

        if proc.poll() is not None:
            show(f"FAIL: the game logged full startup then exited "
                 f"(code {proc.returncode}).")
            return 1

        # Give the frame loop a moment, then confirm it is genuinely running
        # rather than wedged one frame in.  Re-read afterwards: the log is the
        # evidence, and a snapshot taken the instant the marker appeared would
        # under-report everything written in the next few seconds.
        time.sleep(3.0)
        text = log_text(scratch)

        if DEAD_MARK in text:
            show("FAIL: a traceback appeared once the frame loop started:")
            return 1

        if proc.poll() is not None:
            show(f"FAIL: the game died during its first few seconds "
                 f"(code {proc.returncode}).")
            return 1

        lines = [ln for ln in text.splitlines() if ln.strip()]
        print(f"log   : {len(lines)} lines")
        for ln in lines[:8]:
            print(f"        {ln}")
        print("PASS: the exe boots, imports everything, opens the window and runs.")
        return 0

    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                pass
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

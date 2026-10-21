"""Check whether the frozen exe is still running, and tail its log."""

import os
import subprocess
import sys

log = os.path.expandvars(r"%LOCALAPPDATA%\PongPro\logs\pongpro.log")
print("log:", log)
if os.path.exists(log):
    with open(log, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    for line in lines[-25:]:
        print(line.rstrip())
else:
    print("(log file missing)")

out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout
running = [l for l in out.splitlines() if "PongPro" in l]
print("running PongPro processes:", len(running))
for line in running:
    print(" ", line)

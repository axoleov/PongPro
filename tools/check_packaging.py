"""Report the packaging toolchain available in this interpreter."""

import importlib.util

for name in ("setuptools", "wheel", "build", "pyinstaller", "pip"):
    spec = importlib.util.find_spec(name)
    print(f"{name:12} {'present' if spec else 'MISSING'}")

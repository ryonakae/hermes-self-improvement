"""Hermes self-improvement plugin entrypoint.

Keep this file thin: Hermes discovers the plugin at the repository root, while
implementation lives in the hermes_self_improvement package.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

import hermes_self_improvement as _impl

for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


main = _impl.main
register = _impl.register

__all__ = [name for name in globals() if not name.startswith("__")]

if __name__ == "__main__":
    main()

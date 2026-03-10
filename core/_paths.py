"""
core/_paths.py
--------------
Frozen-safe path resolution for dev and PyInstaller --onefile mode.

In dev:          PROJECT_ROOT / DATA_ROOT both point to the repo root
In frozen exe:   PROJECT_ROOT → sys._MEIPASS (read-only bundled assets)
                 DATA_ROOT    → %LOCALAPPDATA%/Auri (writable user data, Windows)
"""
from __future__ import annotations
import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


if _is_frozen():
    # Read-only bundled code + refs live here
    PROJECT_ROOT: Path = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # Writable user data lives next to the exe (survives updates)
    _appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    DATA_ROOT: Path = Path(_appdata) / "Auri"
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DATA_ROOT = PROJECT_ROOT

# Convenience: the "data" subdirectory that all pages use
DATA_DIR = DATA_ROOT / "data"
REFS_ROOT = PROJECT_ROOT / "refs"

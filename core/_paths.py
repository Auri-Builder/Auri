"""
core/_paths.py
--------------
Frozen-safe path resolution for dev and PyInstaller --onefile mode.

In dev:          PROJECT_ROOT / DATA_ROOT both point to the repo root
                 get_data_root() returns PROJECT_ROOT (single profile)
In frozen exe:   PROJECT_ROOT → sys._MEIPASS (read-only bundled assets)
                 DATA_ROOT    → %LOCALAPPDATA%/Auri  (Auri home, profile-unaware)
                 get_data_root() → %LOCALAPPDATA%/Auri/profiles/{active_profile}
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
    # Auri home — writable, survives exe updates
    _appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    _AURI_BASE: Path = Path(_appdata) / "Auri"
    _AURI_BASE.mkdir(parents=True, exist_ok=True)
    # Legacy single-profile root (kept for any direct references)
    DATA_ROOT: Path = _AURI_BASE
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    _AURI_BASE = PROJECT_ROOT
    DATA_ROOT = PROJECT_ROOT

# Legacy convenience constants (dev-safe; pages should use get_data_dir() instead)
DATA_DIR = DATA_ROOT / "data"
REFS_ROOT = PROJECT_ROOT / "refs"


# ── Multi-profile support ──────────────────────────────────────────────────

# Active profile ID — updated by set_active_profile() on every page rerun
_active_profile: str = "default"


def set_active_profile(profile_id: str) -> None:
    """Set the active profile for this process. Call from Home.py on every rerun."""
    global _active_profile
    _active_profile = profile_id or "default"


def get_active_profile() -> str:
    return _active_profile


def get_data_root() -> Path:
    """Return the writable data root for the currently active profile.

    Frozen exe:  %LOCALAPPDATA%/Auri/profiles/{active_profile}
    Dev:         PROJECT_ROOT  (single profile, unchanged behaviour)
    """
    if _is_frozen():
        return _AURI_BASE / "profiles" / _active_profile
    return PROJECT_ROOT


def get_data_dir() -> Path:
    """Return the 'data' subdirectory for the currently active profile."""
    return get_data_root() / "data"


# ── Profile registry (meaningful in frozen exe; stubs work fine in dev) ───

def _profiles_registry_path() -> Path:
    return _AURI_BASE / "profiles.yaml"


def list_profiles() -> list[dict]:
    """Return [{id, display_name, created}] from the registry.

    Returns a synthetic default entry when the registry doesn't exist yet.
    """
    import yaml as _yaml  # lazy
    p = _profiles_registry_path()
    if not p.exists():
        return [{"id": "default", "display_name": "My Portfolio", "created": ""}]
    try:
        data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        profiles = data.get("profiles", [])
        return profiles if profiles else [{"id": "default", "display_name": "My Portfolio", "created": ""}]
    except Exception:
        return [{"id": "default", "display_name": "My Portfolio", "created": ""}]


def create_profile(display_name: str) -> str:
    """Create a new profile folder + registry entry. Returns the new profile id."""
    import re
    import datetime
    import shutil
    import yaml as _yaml  # lazy

    # Slugify display_name → folder-safe id
    profile_id = re.sub(r"[^a-z0-9_-]", "_", display_name.lower().strip())[:30] or "profile"
    existing_ids = {p["id"] for p in list_profiles()}
    base, n = profile_id, 2
    while profile_id in existing_ids:
        profile_id = f"{base}_{n}"
        n += 1

    # Create data subdirectories
    profile_data = _AURI_BASE / "profiles" / profile_id / "data"
    for sub in ["portfolio", "wealth", "retirement", "retirement/scenarios", "derived"]:
        (profile_data / sub).mkdir(parents=True, exist_ok=True)

    # Copy questions.yaml from default profile so the questionnaire works immediately
    default_q = _AURI_BASE / "profiles" / "default" / "data" / "portfolio" / "questions.yaml"
    new_q = profile_data / "portfolio" / "questions.yaml"
    if default_q.exists() and not new_q.exists():
        shutil.copy2(default_q, new_q)

    # Update registry
    profiles = list_profiles()
    # Filter out the synthetic default-only entry if registry didn't exist
    profiles = [p for p in profiles if not (p["id"] == "default" and not p.get("created"))]
    # Ensure default is in the registry
    if not any(p["id"] == "default" for p in profiles):
        profiles.insert(0, {
            "id": "default",
            "display_name": "My Portfolio",
            "created": "",
        })
    profiles.append({
        "id": profile_id,
        "display_name": display_name.strip(),
        "created": datetime.date.today().isoformat(),
    })
    _profiles_registry_path().write_text(
        _yaml.dump({"profiles": profiles}, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    return profile_id


def rename_profile(profile_id: str, new_display_name: str) -> None:
    """Update a profile's display_name in the registry."""
    import yaml as _yaml
    profiles = list_profiles()
    for p in profiles:
        if p["id"] == profile_id:
            p["display_name"] = new_display_name.strip()
            break
    _profiles_registry_path().write_text(
        _yaml.dump({"profiles": profiles}, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

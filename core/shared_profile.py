"""
core/shared_profile.py
----------------------
Shared personal profile — single source of truth for personal details
used across all Auri agents (Portfolio IA, Wealth Builder, Retirement).

Stored at data/shared_profile.yaml (gitignored).

Schema
------
primary:
  name:                  str    e.g. "Jeff"
  current_age:           int
  province:              str    e.g. "BC"
  gross_income:          float  annual employment/self-employment income
  risk_tolerance:        str    conservative | moderate | aggressive
  target_retirement_age: int

spouse:                         (optional — omit or null if no spouse)
  name:                  str    e.g. "Julie"
  current_age:           int
  gross_income:          float

This file intentionally does NOT store account balances — those are derived
from the portfolio CSV at runtime via analytics.compute_account_balance_by_type().
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT  = Path(__file__).resolve().parent.parent
PROFILE_PATH   = _PROJECT_ROOT / "data" / "shared_profile.yaml"

# Provinces supported by the tax engine
PROVINCES = ["BC", "AB", "ON", "QC", "SK", "MB", "NS", "NB", "PE", "NL"]
RISK_LEVELS = ["conservative", "moderate", "aggressive"]


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_shared_profile() -> dict:
    """Load shared profile from disk. Returns empty dict if not found."""
    if not PROFILE_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(PROFILE_PATH.read_text()) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_shared_profile(data: dict) -> None:
    """Persist shared profile to disk."""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROFILE_PATH.open("w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Convenience accessors — return sensible defaults when profile is empty
# ---------------------------------------------------------------------------

def primary(profile: dict | None = None) -> dict:
    p = profile or load_shared_profile()
    return p.get("primary", {})


def spouse(profile: dict | None = None) -> dict | None:
    p = profile or load_shared_profile()
    s = p.get("spouse")
    return s if s else None


def get(key: str, default: Any = None, profile: dict | None = None) -> Any:
    """Shortcut: read a field from primary, with default."""
    return primary(profile).get(key, default)


def has_spouse(profile: dict | None = None) -> bool:
    return spouse(profile) is not None


# ---------------------------------------------------------------------------
# Account balance bridge — reads from portfolio summary
# ---------------------------------------------------------------------------

def get_account_balances() -> dict:
    """
    Return {account_type: balance} from the loaded portfolio CSV.

    e.g. {"RRSP": 120000, "TFSA": 45000, "CASH": 30000}

    Returns empty dict if portfolio not loaded.
    """
    try:
        from core.dashboard_cache import load_summary  # noqa: PLC0415
        summary = load_summary()
        return summary.get("account_balance_by_type", {})
    except Exception:
        return {}


def registered_balance(account_types: list[str] | None = None) -> float:
    """
    Sum of all registered account balances (RRSP + TFSA + RRIF + LIRA etc.)
    or a specific subset if account_types is provided.
    e.g. registered_balance(["RRSP"]) for just RRSP total.
    """
    from agents.ori_ia.schema import REGISTERED_ACCOUNT_TYPES  # noqa: PLC0415
    balances = get_account_balances()
    keys = [k for k in balances if k in (account_types or REGISTERED_ACCOUNT_TYPES)]
    return sum(balances[k] for k in keys)


def non_registered_balance() -> float:
    """Sum of all non-registered (CASH, margin, etc.) account balances."""
    from agents.ori_ia.schema import REGISTERED_ACCOUNT_TYPES  # noqa: PLC0415
    balances = get_account_balances()
    return sum(v for k, v in balances.items() if k not in REGISTERED_ACCOUNT_TYPES)


def tfsa_balance() -> float:
    return get_account_balances().get("TFSA", 0.0)


def rrsp_balance() -> float:
    return get_account_balances().get("RRSP", 0.0)

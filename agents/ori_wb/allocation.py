"""
agents/ori_wb/allocation.py
---------------------------
Asset allocation glide-path model by time horizon and risk tolerance.

Produces a target allocation (equities / bonds / cash) based on:
  - Years to retirement (time horizon)
  - Risk tolerance (conservative / moderate / aggressive)

Also provides a simple "allocation checkup" given current holdings.

Reference: refs/wealth/glide_path.yaml
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_REFS_WEALTH = Path(__file__).parent.parent.parent / "refs" / "wealth"

RiskTolerance = Literal["conservative", "moderate", "aggressive"]


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_glide_path() -> dict:
    import yaml
    path = _REFS_WEALTH / "glide_path.yaml"
    with path.open() as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AllocationTarget:
    equities_pct: float
    bonds_pct:    float
    cash_pct:     float
    horizon_band: str           # e.g. "10-15"
    risk:         RiskTolerance

    @property
    def total(self) -> float:
        return self.equities_pct + self.bonds_pct + self.cash_pct


@dataclass
class AllocationCheckup:
    target:             AllocationTarget
    current_equities:   float   # %
    current_bonds:      float   # %
    current_cash:       float   # %
    drift_equities:     float   # current - target (positive = overweight)
    drift_bonds:        float
    drift_cash:         float
    max_drift:          float   # largest absolute drift
    needs_rebalance:    bool    # True if any bucket drifts > threshold
    rebalance_threshold: float  # default 5 pp


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _horizon_band(years: int) -> str:
    if years > 25:    return ">25"
    if years >= 20:   return "20-25"
    if years >= 15:   return "15-20"
    if years >= 10:   return "10-15"
    if years >= 5:    return "5-10"
    if years >= 2:    return "2-5"
    return "<2"


def target_allocation(
    years_to_retirement: int,
    risk: RiskTolerance = "moderate",
) -> AllocationTarget:
    """Return the target allocation for the given horizon and risk tolerance."""
    gp   = _load_glide_path()
    band = _horizon_band(years_to_retirement)
    row  = gp[risk][band]   # [equities%, bonds%, cash%]
    return AllocationTarget(
        equities_pct = float(row[0]),
        bonds_pct    = float(row[1]),
        cash_pct     = float(row[2]),
        horizon_band = band,
        risk         = risk,
    )


def allocation_checkup(
    years_to_retirement: int,
    risk: RiskTolerance,
    current_equities_pct: float,
    current_bonds_pct:    float,
    current_cash_pct:     float,
    rebalance_threshold:  float = 5.0,  # percentage points
) -> AllocationCheckup:
    """Compare current allocation to target and flag drift."""
    tgt = target_allocation(years_to_retirement, risk)
    d_eq   = current_equities_pct - tgt.equities_pct
    d_bd   = current_bonds_pct    - tgt.bonds_pct
    d_cash = current_cash_pct     - tgt.cash_pct
    max_d  = max(abs(d_eq), abs(d_bd), abs(d_cash))
    return AllocationCheckup(
        target               = tgt,
        current_equities     = current_equities_pct,
        current_bonds        = current_bonds_pct,
        current_cash         = current_cash_pct,
        drift_equities       = d_eq,
        drift_bonds          = d_bd,
        drift_cash           = d_cash,
        max_drift            = max_d,
        needs_rebalance      = max_d >= rebalance_threshold,
        rebalance_threshold  = rebalance_threshold,
    )


def all_risk_targets(years_to_retirement: int) -> dict[str, AllocationTarget]:
    """Return targets for all three risk levels — for comparison display."""
    return {
        r: target_allocation(years_to_retirement, r)  # type: ignore[arg-type]
        for r in ("conservative", "moderate", "aggressive")
    }

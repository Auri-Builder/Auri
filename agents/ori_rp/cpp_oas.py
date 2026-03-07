"""
agents/ori_rp/cpp_oas.py
--------------------------
CPP and OAS benefit calculation by start age.

Adjustment factors are loaded from:
  refs/retirement/cpp_adjustments.yaml
  refs/retirement/oas_adjustments.yaml

All benefit amounts are in today's dollars (real). The cashflow engine
applies inflation indexing year-by-year after this module returns the
base amount.

Disclaimer: CPP and OAS calculations are illustrative — use your
My Service Canada statement for accurate benefit figures.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_REFS_DIR = Path(__file__).parent.parent.parent / "refs" / "retirement"


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_cpp_adjustments() -> dict[int, float]:
    """Load CPP actuarial adjustment factors {start_age: factor}."""
    import yaml
    path = _REFS_DIR / "cpp_adjustments.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    return {int(k): float(v) for k, v in data["adjustments"].items()}


@lru_cache(maxsize=1)
def _load_oas_adjustments() -> dict[int, float]:
    """Load OAS deferral increase factors {start_age: factor}."""
    import yaml
    path = _REFS_DIR / "oas_adjustments.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    return {int(k): float(v) for k, v in data["adjustments"].items()}


# ---------------------------------------------------------------------------
# CPP benefit
# ---------------------------------------------------------------------------

def cpp_monthly_benefit(
    cpp_monthly_at_65: float,
    start_age: int,
) -> float:
    """
    Compute the adjusted CPP monthly benefit for a given start age.

    Parameters
    ----------
    cpp_monthly_at_65 : float
        The investor's CPP entitlement at age 65, in today's dollars.
        Obtain from My Service Canada account.
    start_age : int
        Age at which CPP begins. Valid range: 60–70.
        Values outside this range are clamped.

    Returns
    -------
    float : Monthly CPP benefit in today's dollars.
    """
    factors = _load_cpp_adjustments()
    clamped = max(60, min(70, start_age))
    if clamped != start_age:
        logger.warning("cpp_oas: CPP start age %d clamped to %d", start_age, clamped)

    factor = factors.get(clamped, 1.0)
    return round(cpp_monthly_at_65 * factor, 2)


def cpp_annual_benefit(cpp_monthly_at_65: float, start_age: int) -> float:
    """Annual CPP income in today's dollars."""
    return round(cpp_monthly_benefit(cpp_monthly_at_65, start_age) * 12, 2)


# ---------------------------------------------------------------------------
# OAS benefit
# ---------------------------------------------------------------------------

def oas_monthly_benefit(
    oas_monthly_at_65: float,
    start_age: int,
) -> float:
    """
    Compute the adjusted OAS monthly benefit for a given start age.

    Parameters
    ----------
    oas_monthly_at_65 : float
        The investor's OAS entitlement at age 65 (full residency),
        in today's dollars.
    start_age : int
        Age at which OAS begins. Valid range: 65–70.
        Values below 65 are clamped to 65; values above 70 clamped to 70.

    Returns
    -------
    float : Monthly OAS benefit in today's dollars.
    """
    factors = _load_oas_adjustments()
    clamped = max(65, min(70, start_age))
    if clamped != start_age:
        logger.warning("cpp_oas: OAS start age %d clamped to %d", start_age, clamped)

    factor = factors.get(clamped, 1.0)
    return round(oas_monthly_at_65 * factor, 2)


def oas_annual_benefit(oas_monthly_at_65: float, start_age: int) -> float:
    """Annual OAS income in today's dollars."""
    return round(oas_monthly_benefit(oas_monthly_at_65, start_age) * 12, 2)


# ---------------------------------------------------------------------------
# Break-even analysis
# ---------------------------------------------------------------------------

def cpp_breakeven_age(cpp_monthly_at_65: float, start_age: int, compare_age: int = 65) -> int | None:
    """
    Compute the age at which cumulative CPP income from start_age exceeds
    cumulative CPP income from compare_age.

    Returns None if start_age >= compare_age (no break-even needed) or
    if the break-even is never reached within the planning horizon (age 100).

    This is a simple nominal (non-discounted) cumulative comparison.
    """
    if start_age >= compare_age:
        return None

    monthly_early  = cpp_monthly_benefit(cpp_monthly_at_65, start_age)
    monthly_base   = cpp_monthly_benefit(cpp_monthly_at_65, compare_age)

    # At age start_age, early payments begin; base payments begin at compare_age.
    # Accumulate month by month until cumulative_early >= cumulative_base.
    cumulative_early = 0.0
    cumulative_base  = 0.0
    current_month    = start_age * 12

    for month in range(start_age * 12, 100 * 12):
        age_now = month / 12
        cumulative_early += monthly_early
        if age_now >= compare_age:
            cumulative_base += monthly_base
        if cumulative_early >= cumulative_base and age_now >= compare_age:
            return int(age_now) + 1  # year of break-even

    return None  # break-even not reached by age 100


def cpp_timing_comparison(cpp_monthly_at_65: float) -> list[dict]:
    """
    Return a table of CPP benefit and break-even data for all valid start ages (60–70).

    Useful for the "CPP/OAS Timing" UI section.

    Returns list of dicts, one per start age:
        start_age, monthly_benefit, annual_benefit, factor_pct,
        breakeven_vs_65 (int | None)
    """
    rows = []
    for age in range(60, 71):
        monthly = cpp_monthly_benefit(cpp_monthly_at_65, age)
        factors = _load_cpp_adjustments()
        factor  = factors.get(age, 1.0)
        rows.append({
            "start_age":        age,
            "monthly_benefit":  monthly,
            "annual_benefit":   round(monthly * 12, 2),
            "factor_pct":       round((factor - 1.0) * 100, 1),  # e.g. -36.0 or +42.0
            "breakeven_vs_65":  cpp_breakeven_age(cpp_monthly_at_65, age, compare_age=65),
        })
    return rows


def oas_timing_comparison(oas_monthly_at_65: float) -> list[dict]:
    """
    Return a table of OAS benefit data for start ages 65–70.

    Returns list of dicts:
        start_age, monthly_benefit, annual_benefit, factor_pct,
        breakeven_vs_65 (int | None)
    """
    rows = []
    factors = _load_oas_adjustments()
    for age in range(65, 71):
        monthly = oas_monthly_benefit(oas_monthly_at_65, age)
        factor  = factors.get(age, 1.0)
        # Break-even for OAS (nominal)
        be = _oas_breakeven(oas_monthly_at_65, age, compare_age=65) if age > 65 else None
        rows.append({
            "start_age":        age,
            "monthly_benefit":  monthly,
            "annual_benefit":   round(monthly * 12, 2),
            "factor_pct":       round((factor - 1.0) * 100, 1),
            "breakeven_vs_65":  be,
        })
    return rows


def _oas_breakeven(oas_monthly_at_65: float, start_age: int, compare_age: int = 65) -> int | None:
    """Nominal cumulative OAS break-even age (deferral vs taking at compare_age)."""
    if start_age <= compare_age:
        return None

    monthly_deferred = oas_monthly_benefit(oas_monthly_at_65, start_age)
    monthly_base     = oas_monthly_benefit(oas_monthly_at_65, compare_age)

    cumulative_deferred = 0.0
    cumulative_base     = 0.0

    for month_idx in range(compare_age * 12, 100 * 12):
        age_now = month_idx / 12
        cumulative_base += monthly_base
        if age_now >= start_age:
            cumulative_deferred += monthly_deferred
        if cumulative_deferred >= cumulative_base and age_now >= start_age:
            return int(age_now) + 1

    return None
